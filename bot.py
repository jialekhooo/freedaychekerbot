import csv
import io
import json
import os
import re
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

DATA_DIR = Path(os.getenv("BOT_DATA_DIR", str(Path(__file__).resolve().parent / "data")))
DATA_FILE = DATA_DIR / "storage.json"

WEEKDAY_ALIASES = {
    "mon": 0,
    "monday": 0,
    "tue": 1,
    "tues": 1,
    "tuesday": 1,
    "wed": 2,
    "wednesday": 2,
    "thu": 3,
    "thur": 3,
    "thurs": 3,
    "thursday": 3,
    "fri": 4,
    "friday": 4,
    "sat": 5,
    "saturday": 5,
    "sun": 6,
    "sunday": 6,
}

MONTH_NAME_ALIASES = {
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}


def ensure_storage() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not DATA_FILE.exists():
        DATA_FILE.write_text(
            json.dumps({"shifts": [], "plans": [], "default_rate": None}, indent=2),
            encoding="utf-8",
        )


def load_state() -> dict:
    ensure_storage()
    try:
        with DATA_FILE.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (json.JSONDecodeError, OSError):
        data = {"shifts": [], "plans": [], "default_rate": None}

    data.setdefault("shifts", [])
    data.setdefault("plans", [])
    data.setdefault("default_rate", None)
    return data


def save_state(state: dict) -> None:
    ensure_storage()
    with DATA_FILE.open("w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=2)


def format_currency(value: Decimal | int | float) -> str:
    amount = Decimal(str(value))
    return f"${amount.quantize(Decimal('0.01')):,.2f}"


def parse_date_string(value: str | None) -> date:
    today = date.today()
    if value is None:
        return today

    token = value.strip().lower()
    if not token:
        return today
    if token in {"today", "tod"}:
        return today
    if token in {"tomorrow", "tmr", "tmrw"}:
        return today + timedelta(days=1)
    if token in WEEKDAY_ALIASES:
        target_index = WEEKDAY_ALIASES[token]
        delta = (target_index - today.weekday()) % 7
        return today + timedelta(days=delta)
    if token.startswith("next "):
        weekday_name = token[5:].strip()
        if weekday_name in WEEKDAY_ALIASES:
            target_index = WEEKDAY_ALIASES[weekday_name]
            delta = (target_index - today.weekday() + 7) % 7
            next_day = today + timedelta(days=delta or 7)
            return next_day

    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value.strip(), fmt).date()
        except ValueError:
            continue

    for fmt in ("%d/%m", "%d-%m"):
        try:
            return datetime.strptime(value.strip(), fmt).date().replace(year=today.year)
        except ValueError:
            continue

    return today


def parse_time_value(raw: str) -> str:
    text = raw.strip().lower().replace(" ", "")
    if not text:
        return ""
    if re.fullmatch(r"\d{1,2}:\d{2}(?:am|pm)?", text):
        return text
    if re.fullmatch(r"\d{1,2}(?:am|pm)", text):
        return text
    if re.fullmatch(r"\d{1,2}:\d{2}", text):
        return text
    if re.fullmatch(r"\d{1,2}", text):
        return text
    return text


def parse_clock_time(raw: str) -> tuple[int, int] | None:
    text = raw.strip().lower().replace(" ", "").replace(".", ":")
    match = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?(am|pm)?", text)
    if not match:
        return None

    hour = int(match.group(1))
    minute = int(match.group(2)) if match.group(2) else 0
    meridian = match.group(3)
    if meridian == "pm" and hour != 12:
        hour += 12
    if meridian == "am" and hour == 12:
        hour = 0
    if not (0 <= hour < 24 and 0 <= minute < 60):
        return None
    return hour, minute


def parse_plan_text(raw_text: str) -> dict:
    text = raw_text.strip()
    date_value = date.today().isoformat()
    start_time = ""
    end_time = ""
    repeat = None

    repeat_match = re.search(r"(?i)\bevery\s+(day|daily|mon|monday|tue|tues|tuesday|wed|wednesday|thu|thur|thurs|thursday|fri|friday|sat|saturday|sun|sunday)\b", text)
    if repeat_match:
        token = repeat_match.group(1).lower()
        repeat = "daily" if token in {"day", "daily"} else f"weekly:{WEEKDAY_ALIASES[token]}"
        text = text[: repeat_match.start()] + " " + text[repeat_match.end() :]

    for match in re.finditer(r"(?i)\b(today|tomorrow|mon|monday|tue|tues|tuesday|wed|wednesday|thu|thur|thurs|thursday|fri|friday|sat|saturday|sun|sunday|next\s+(?:mon|monday|tue|tues|tuesday|wed|wednesday|thu|thur|thurs|thursday|fri|friday|sat|saturday|sun|sunday)|\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?|\d{4}-\d{2}-\d{2})\b", text):
        token = match.group(0)
        date_value = parse_date_string(token).isoformat()
        text = text[: match.start()] + " " + text[match.end() :]
        break

    time_range_match = re.search(
        r"(?i)(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)\s*(?:-|to)\s*(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)",
        text,
    )
    if time_range_match:
        start_time = parse_time_value(time_range_match.group(1))
        end_time = parse_time_value(time_range_match.group(2))
        text = text[: time_range_match.start()] + " " + text[time_range_match.end() :]

    single_time_match = re.search(r"(?i)\b(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)\b", text)
    if not time_range_match and single_time_match:
        start_time = parse_time_value(single_time_match.group(1))
        text = text[: single_time_match.start()] + " " + text[single_time_match.end() :]

    title = re.sub(r"\s+", " ", text).strip() or "Untitled plan"
    return {
        "date": date_value,
        "start_time": start_time,
        "end_time": end_time,
        "title": title,
        "repeat": repeat,
        "done": False,
    }


def add_plan(state: dict, raw_text: str) -> dict:
    parsed = parse_plan_text(raw_text)
    plan_id = len(state["plans"]) + 1
    plan = {
        "id": plan_id,
        "title": parsed["title"],
        "date": parsed["date"],
        "start_time": parsed["start_time"],
        "end_time": parsed["end_time"],
        "repeat": parsed["repeat"],
        "done": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    state["plans"].append(plan)
    return plan


def mark_plan_done(state: dict, plan_id: int) -> bool:
    for plan in state["plans"]:
        if plan["id"] == plan_id:
            plan["done"] = True
            return True
    return False


def delete_plan(state: dict, plan_id: int) -> bool:
    before = len(state["plans"])
    state["plans"] = [plan for plan in state["plans"] if plan["id"] != plan_id]
    return len(state["plans"]) != before


def parse_rate_value(text: str) -> Decimal | None:
    match = re.search(r"(?i)\$?(\d+(?:\.\d+)?)\s*(?:/\s*h(?:r|our)?|per\s*hour)", text)
    if not match:
        return None
    return Decimal(match.group(1))


def parse_shift_text(raw_text: str, default_rate: Decimal | None) -> dict:
    text = raw_text.strip()

    location = None
    loc_match = re.search(r"(?i)\s+(?:@|at)\s+(.+)$", text)
    if loc_match:
        location = loc_match.group(1).strip()
        text = text[: loc_match.start()]

    rate = None
    rate_match = re.search(r"(?i)\$?(\d+(?:\.\d+)?)\s*(?:/\s*h(?:r|our)?|per\s*hour)", text)
    if rate_match:
        rate = Decimal(rate_match.group(1))
        text = text[: rate_match.start()] + " " + text[rate_match.end() :]

    date_value = date.today().isoformat()
    for match in re.finditer(r"(?i)\b(today|tomorrow|mon|monday|tue|tues|tuesday|wed|wednesday|thu|thur|thurs|thursday|fri|friday|sat|saturday|sun|sunday|next\s+(?:mon|monday|tue|tues|tuesday|wed|wednesday|thu|thur|thurs|thursday|fri|friday|sat|saturday|sun|sunday)|\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?|\d{4}-\d{2}-\d{2})\b", text):
        date_value = parse_date_string(match.group(0)).isoformat()
        text = text[: match.start()] + " " + text[match.end() :]
        break

    start_hm = None
    end_hm = None
    time_range_match = re.search(
        r"(?i)(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)\s*(?:-|to)\s*(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)",
        text,
    )
    if time_range_match:
        start_hm = parse_clock_time(time_range_match.group(1))
        end_hm = parse_clock_time(time_range_match.group(2))
        text = text[: time_range_match.start()] + " " + text[time_range_match.end() :]

    name = re.sub(r"\s+", " ", text).strip() or "Shift"
    return {
        "date": date_value,
        "start_hm": start_hm,
        "end_hm": end_hm,
        "rate": rate if rate is not None else default_rate,
        "name": name,
        "location": location,
    }


def compute_shift_hours(start_hm: tuple[int, int] | None, end_hm: tuple[int, int] | None) -> Decimal:
    if not start_hm or not end_hm:
        return Decimal("0")
    start_minutes = start_hm[0] * 60 + start_hm[1]
    end_minutes = end_hm[0] * 60 + end_hm[1]
    if end_minutes <= start_minutes:
        end_minutes += 24 * 60
    return Decimal(end_minutes - start_minutes) / Decimal(60)


def add_shift(state: dict, parsed: dict) -> dict:
    hours = compute_shift_hours(parsed["start_hm"], parsed["end_hm"])
    pay = (hours * parsed["rate"]).quantize(Decimal("0.01"))
    shift_id = len(state["shifts"]) + 1
    shift = {
        "id": shift_id,
        "date": parsed["date"],
        "start_time": f"{parsed['start_hm'][0]:02d}:{parsed['start_hm'][1]:02d}",
        "end_time": f"{parsed['end_hm'][0]:02d}:{parsed['end_hm'][1]:02d}",
        "rate": str(parsed["rate"]),
        "hours": str(hours),
        "pay": str(pay),
        "name": parsed["name"],
        "location": parsed.get("location") or "",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    state["shifts"].append(shift)
    return shift


def format_shift_item(shift: dict) -> str:
    location = f" @ {shift['location']}" if shift.get("location") else ""
    return (
        f"#{shift['id']} {shift['date']} {shift['start_time']}-{shift['end_time']} "
        f"{shift['name']}{location} \u2014 {shift['hours']}h @ {format_currency(Decimal(shift['rate']))}/h "
        f"= {format_currency(Decimal(shift['pay']))}"
    )


def get_default_rate(state: dict) -> Decimal | None:
    rate = state.get("default_rate")
    return Decimal(rate) if rate else None


def set_default_rate(state: dict, amount: Decimal) -> None:
    state["default_rate"] = str(amount)


def total_pay(state: dict) -> Decimal:
    return sum((Decimal(item["pay"]) for item in state["shifts"]), Decimal("0"))


def shifts_for_month(state: dict, year: int, month: int) -> list:
    prefix = f"{year:04d}-{month:02d}"
    return [item for item in state["shifts"] if item["date"].startswith(prefix)]


def build_shifts_csv(state: dict) -> str:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["id", "date", "start", "end", "name", "location", "rate", "hours", "pay"])
    for item in state["shifts"]:
        writer.writerow(
            [
                item["id"],
                item["date"],
                item["start_time"],
                item["end_time"],
                item["name"],
                item["location"],
                item["rate"],
                item["hours"],
                item["pay"],
            ]
        )
    return output.getvalue()


def parse_month_string(value: str | None) -> tuple[int, int]:
    today = date.today()
    if not value or not value.strip():
        return today.year, today.month

    token = value.strip().lower()
    if token in {"this month", "thismonth"}:
        return today.year, today.month
    if token in {"last month", "lastmonth"}:
        last_month_date = today.replace(day=1) - timedelta(days=1)
        return last_month_date.year, last_month_date.month

    iso_match = re.fullmatch(r"(\d{4})-(\d{2})", token)
    if iso_match:
        return int(iso_match.group(1)), int(iso_match.group(2))

    words = token.split()
    month_word = words[0] if words else token
    if month_word in MONTH_NAME_ALIASES:
        month_num = MONTH_NAME_ALIASES[month_word]
        year = int(words[1]) if len(words) > 1 and words[1].isdigit() else today.year
        return year, month_num

    if token.isdigit() and 1 <= int(token) <= 12:
        return today.year, int(token)

    return today.year, today.month


def build_month_summary(state: dict, year: int, month: int) -> str:
    shifts = shifts_for_month(state, year, month)
    label = date(year, month, 1).strftime("%B %Y")
    if not shifts:
        return f"No shifts logged for {label}."

    total_hours = sum((Decimal(item["hours"]) for item in shifts), Decimal("0"))
    total_pay_amount = sum((Decimal(item["pay"]) for item in shifts), Decimal("0"))

    lines = [f"{label}: {format_currency(total_pay_amount)} across {total_hours}h ({len(shifts)} shifts)", ""]
    lines.extend(format_shift_item(item) for item in shifts)
    return "\n".join(lines)


def plans_for_date(state: dict, target_date: str) -> list:
    normalized = parse_date_string(target_date).isoformat()
    target = date.fromisoformat(normalized)
    matches = []
    for plan in state["plans"]:
        if plan["date"] == normalized:
            matches.append(plan)
            continue
        repeat = plan.get("repeat")
        if not repeat or plan["date"] > normalized:
            continue
        if repeat == "daily" or repeat == f"weekly:{target.weekday()}":
            matches.append(plan)
    return matches


def get_reminder_settings(state: dict, chat_id: int | str) -> dict:
    reminders = state.setdefault("reminders", {})
    return reminders.setdefault(str(chat_id), {"enabled": False, "time": "08:00", "tz_offset": 8, "reminded_today": {}})


def set_reminder_enabled(state: dict, chat_id: int | str, enabled: bool) -> dict:
    cfg = get_reminder_settings(state, chat_id)
    cfg["enabled"] = enabled
    return cfg


def set_reminder_time(state: dict, chat_id: int | str, time_str: str, tz_offset: int | None = None) -> dict:
    cfg = get_reminder_settings(state, chat_id)
    cfg["time"] = time_str
    cfg["enabled"] = True
    if tz_offset is not None:
        cfg["tz_offset"] = tz_offset
    return cfg


def local_time_for_offset(tz_offset: int) -> datetime:
    return datetime.now(timezone.utc) + timedelta(hours=tz_offset)


def plans_starting_soon(plans: list, local_now: datetime, window_minutes: int = 30) -> list:
    due = []
    for plan in plans:
        if plan["done"] or not plan.get("start_time"):
            continue
        parsed = parse_clock_time(plan["start_time"])
        if not parsed:
            continue
        plan_dt = local_now.replace(hour=parsed[0], minute=parsed[1], second=0, microsecond=0)
        delta_minutes = (plan_dt - local_now).total_seconds() / 60
        if 0 <= delta_minutes <= window_minutes:
            due.append(plan)
    return due


def build_agenda_message(plans: list) -> str:
    if not plans:
        return "Good morning! Nothing on today's agenda."
    lines = ["Good morning! Today's agenda:"]
    lines.extend(format_plan_item(plan) for plan in plans)
    return "\n".join(lines)


def summary_text(state: dict, target_date: str | None = None) -> str:
    today_value = parse_date_string(target_date).isoformat() if target_date else date.today().isoformat()
    today = date.fromisoformat(today_value)
    month_shifts = shifts_for_month(state, today.year, today.month)
    month_pay = sum((Decimal(item["pay"]) for item in month_shifts), Decimal("0"))
    month_hours = sum((Decimal(item["hours"]) for item in month_shifts), Decimal("0"))
    all_time_pay = total_pay(state)
    open_today = sum(1 for item in plans_for_date(state, today_value) if not item["done"])
    done_today = sum(1 for item in plans_for_date(state, today_value) if item["done"])
    all_open = sum(1 for item in state["plans"] if not item["done"])

    return (
        "Daily overview:\n"
        f"- This month's pay: {format_currency(month_pay)} ({month_hours}h, {len(month_shifts)} shifts)\n"
        f"- All-time pay: {format_currency(all_time_pay)}\n"
        f"- Planned today: {open_today} open, {done_today} done\n"
        f"- All open plans: {all_open}"
    )


def format_plan_item(plan: dict) -> str:
    status = "✅" if plan["done"] else "⏳"
    repeat_marker = " 🔁" if plan.get("repeat") else ""
    if plan.get("start_time") and plan.get("end_time"):
        return f"#{plan['id']} {status} {plan['date']} {plan['start_time']}-{plan['end_time']} {plan['title']}{repeat_marker}"
    if plan.get("start_time"):
        return f"#{plan['id']} {status} {plan['date']} {plan['start_time']} {plan['title']}{repeat_marker}"
    return f"#{plan['id']} {status} {plan['date']} {plan['title']}{repeat_marker}"


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    help_text = (
        "Welcome to your pay + daily planner bot.\n\n"
        "Just send a plain message like 'tomorrow 4pm gym' to add a plan - no command needed.\n\n"
        "Core commands:\n"
        "- /plan add today 2pm-4pm finish report\n"
        "- /plan add every mon 9am gym (recurring)\n"
        "- /plan list\n"
        "- /plan done 1\n"
        "- /today\n"
        "- /week\n"
        "- /pay add 13/8 8.30am-8pm 15/h Wedding gig @ MBS\n"
        "- /pay rate 15\n"
        "- /pay total\n"
        "- /month [aug|2026-08|last month]\n"
        "- /summary\n"
        "- /commands\n"
        "- /help"
    )
    await update.message.reply_text(help_text)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await start(update, context)


async def commands_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lines = [
        "All commands:",
        "Plain message (no command) - quick-add a plan, e.g. 'fri 3pm dentist'",
        "/plan add <text> - add a plan (supports today/tomorrow/weekday, time ranges, 'every mon')",
        "/plan list - show every plan",
        "/plan done <id> - mark a plan done",
        "/plan delete <id> - remove a plan",
        "/today - today's plans",
        "/week - next 7 days of plans",
        "/pay add <shift line> - log a shift, e.g. '13/8 8.30am-8pm 15/h Wedding gig @ MBS'",
        "/pay list - recent shifts",
        "/pay total [month] - total pay for a month (default: this month)",
        "/pay rate 15 - set your default hourly rate",
        "/pay delete <id> - remove a shift",
        "/month [aug|2026-08|last month] - monthly pay breakdown",
        "/export - CSV export of shifts",
        "/reminders on|off|07:30 [+8] - daily agenda + heads-up before plans",
        "/summary - daily overview of pay + plans",
    ]
    await update.message.reply_text("\n".join(lines))


async def plan_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    state = load_state()
    args = context.args

    if not args:
        await update.message.reply_text(
            "Usage:\n"
            "- /plan add today 2pm-4pm Finish report\n"
            "- /plan list\n"
            "- /plan done 1\n"
            "- /plan delete 1"
        )
        return

    action = args[0].lower()

    if action == "add":
        text = " ".join(args[1:])
        if not text:
            await update.message.reply_text("Usage: /plan add tomorrow 4pm follow up with team")
            return
        plan = add_plan(state, text)
        save_state(state)
        await update.message.reply_text(f"Added plan: {format_plan_item(plan)}")
        return

    if action == "list":
        if not state["plans"]:
            await update.message.reply_text("No plans yet.")
            return
        lines = ["Your plans:"]
        for plan in state["plans"]:
            lines.append(format_plan_item(plan))
        await update.message.reply_text("\n".join(lines))
        return

    if action == "done":
        if len(args) < 2:
            await update.message.reply_text("Usage: /plan done 1")
            return
        try:
            plan_id = int(args[1])
        except ValueError:
            await update.message.reply_text("Plan ID must be a number.")
            return
        if not mark_plan_done(state, plan_id):
            await update.message.reply_text(f"No plan found with ID {plan_id}.")
            return
        save_state(state)
        await update.message.reply_text(f"Marked plan #{plan_id} as done.")
        return

    if action == "delete":
        if len(args) < 2:
            await update.message.reply_text("Usage: /plan delete 1")
            return
        try:
            plan_id = int(args[1])
        except ValueError:
            await update.message.reply_text("Plan ID must be a number.")
            return
        if not delete_plan(state, plan_id):
            await update.message.reply_text(f"No plan found with ID {plan_id}.")
            return
        save_state(state)
        await update.message.reply_text(f"Removed plan #{plan_id}.")
        return

    await update.message.reply_text("Unknown plan command. Try /plan add, /plan list, /plan done or /plan delete.")


async def today_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    state = load_state()
    today_value = date.today().isoformat()
    plans = plans_for_date(state, today_value)
    if not plans:
        message = "Today is clear.\n- No plans scheduled.\n- All-time pay: " + format_currency(total_pay(state))
        await update.message.reply_text(message)
        return

    lines = ["Today:"]
    for plan in plans:
        status = "✅" if plan["done"] else "⏳"
        lines.append(f"{status} {format_plan_item(plan)}")
    await update.message.reply_text("\n".join(lines))


async def week_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    state = load_state()
    lines = ["This week:"]
    for offset in range(7):
        day = date.today() + timedelta(days=offset)
        day_plans = plans_for_date(state, day.isoformat())
        label = "Today" if offset == 0 else day.strftime("%a %d %b")
        if not day_plans:
            continue
        lines.append(f"\n{label}:")
        for plan in day_plans:
            status = "✅" if plan["done"] else "⏳"
            lines.append(f"{status} {format_plan_item(plan)}")

    if len(lines) == 1:
        lines.append("Nothing planned for the next 7 days.")
    await update.message.reply_text("\n".join(lines))


async def pay_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    state = load_state()
    args = context.args
    if not args:
        await update.message.reply_text(
            "Usage:\n"
            "- /pay add 13/8 8.30am-8pm 15/h Wedding gig @ Marina Bay Sands\n"
            "- /pay list\n"
            "- /pay total [month]\n"
            "- /pay rate 15\n"
            "- /pay delete 1"
        )
        return

    action = args[0].lower()

    if action == "add":
        text = " ".join(args[1:])
        if not text:
            await update.message.reply_text("Usage: /pay add 13/8 8.30am-8pm 15/h Wedding gig @ Marina Bay Sands")
            return

        default_rate = get_default_rate(state)
        parsed = parse_shift_text(text, default_rate)

        if not parsed["start_hm"] or not parsed["end_hm"]:
            await update.message.reply_text("Couldn't find a time range, e.g. 8.30am-8pm.")
            return

        if parsed["rate"] is None:
            await update.message.reply_text(
                "No rate given and no default rate set. Use /pay rate 15, or include a rate like '15/h' in the line."
            )
            return

        shift = add_shift(state, parsed)
        save_state(state)
        await update.message.reply_text(f"Logged shift: {format_shift_item(shift)}")
        return

    if action == "list":
        if not state["shifts"]:
            await update.message.reply_text("No shifts logged yet.")
            return
        lines = ["Recent shifts:"]
        for item in reversed(state["shifts"]):
            lines.append(format_shift_item(item))
        await update.message.reply_text("\n".join(lines))
        return

    if action in {"total", "earnings"}:
        value = " ".join(args[1:]) if len(args) > 1 else None
        year, month = parse_month_string(value)
        await update.message.reply_text(build_month_summary(state, year, month))
        return

    if action == "rate":
        if len(args) < 2:
            current = get_default_rate(state)
            message = f"Default rate: {format_currency(current)}/h" if current is not None else "No default rate set. Use /pay rate 15."
            await update.message.reply_text(message)
            return
        try:
            amount = Decimal(args[1])
        except InvalidOperation:
            await update.message.reply_text("Rate must be a valid number, e.g. 15 or 17.50")
            return
        set_default_rate(state, amount)
        save_state(state)
        await update.message.reply_text(f"Default rate set to {format_currency(amount)}/h")
        return

    if action == "delete":
        if len(args) < 2:
            await update.message.reply_text("Usage: /pay delete 1")
            return
        try:
            shift_id = int(args[1])
        except ValueError:
            await update.message.reply_text("Shift ID must be a number.")
            return
        remaining = [item for item in state["shifts"] if item["id"] != shift_id]
        if len(remaining) == len(state["shifts"]):
            await update.message.reply_text(f"No shift found with ID {shift_id}.")
            return
        state["shifts"] = remaining
        save_state(state)
        await update.message.reply_text(f"Removed shift #{shift_id}.")
        return

    await update.message.reply_text("Unknown pay command. Try /pay add, /pay list, /pay total, /pay rate or /pay delete.")


async def summary_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    state = load_state()
    await update.message.reply_text(summary_text(state, date.today().isoformat()))


async def month_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    state = load_state()
    value = " ".join(context.args) if context.args else None
    year, month = parse_month_string(value)
    await update.message.reply_text(build_month_summary(state, year, month))


async def plain_text_plan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = update.message.text
    if not text or not text.strip():
        return
    state = load_state()
    plan = add_plan(state, text)
    save_state(state)
    await update.message.reply_text(f"Added plan: {format_plan_item(plan)}")


async def export_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    state = load_state()
    if not state["shifts"]:
        await update.message.reply_text("No shifts to export yet.")
        return
    csv_text = build_shifts_csv(state)
    buffer = io.BytesIO(csv_text.encode("utf-8"))
    buffer.name = "shifts.csv"
    await update.message.reply_document(document=buffer, filename="shifts.csv", caption="Shift export")


async def reminders_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    state = load_state()
    chat_id = update.effective_chat.id
    args = context.args

    if not args:
        cfg = get_reminder_settings(state, chat_id)
        status = "on" if cfg["enabled"] else "off"
        await update.message.reply_text(
            f"Reminders are {status}. Time: {cfg['time']} (UTC{cfg['tz_offset']:+d}).\n"
            "Usage: /reminders on|off|07:30 [+8]"
        )
        return

    token = args[0].lower()
    if token == "on":
        set_reminder_enabled(state, chat_id, True)
        save_state(state)
        await update.message.reply_text("Reminders turned on.")
        return

    if token == "off":
        set_reminder_enabled(state, chat_id, False)
        save_state(state)
        await update.message.reply_text("Reminders turned off.")
        return

    parsed_time = parse_clock_time(token)
    if not parsed_time:
        await update.message.reply_text("Usage: /reminders on|off|07:30 [+8]")
        return

    tz_offset = None
    if len(args) > 1:
        try:
            tz_offset = int(args[1].replace("+", ""))
        except ValueError:
            tz_offset = None

    time_str = f"{parsed_time[0]:02d}:{parsed_time[1]:02d}"
    set_reminder_time(state, chat_id, time_str, tz_offset)
    save_state(state)
    await update.message.reply_text(f"Reminders set for {time_str} daily.")


async def reminder_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    state = load_state()
    changed = False

    for chat_id, cfg in state.get("reminders", {}).items():
        if not cfg.get("enabled"):
            continue

        local_now = local_time_for_offset(cfg.get("tz_offset", 8))
        today_iso = local_now.date().isoformat()
        todays_plans = plans_for_date(state, today_iso)

        if local_now.strftime("%H:%M") == cfg.get("time", "08:00") and cfg.get("last_agenda_date") != today_iso:
            await context.bot.send_message(chat_id=int(chat_id), text=build_agenda_message(todays_plans))
            cfg["last_agenda_date"] = today_iso
            changed = True

        reminded_today = cfg.setdefault("reminded_today", {})
        for plan in plans_starting_soon(todays_plans, local_now):
            plan_key = str(plan["id"])
            if reminded_today.get(plan_key) == today_iso:
                continue
            await context.bot.send_message(chat_id=int(chat_id), text=f"Heads up soon: {format_plan_item(plan)}")
            reminded_today[plan_key] = today_iso
            changed = True

    if changed:
        save_state(state)


def main() -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("Missing TELEGRAM_BOT_TOKEN. Add it to your environment or .env file.")

    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("plan", plan_command))
    app.add_handler(CommandHandler("add", plan_command))
    app.add_handler(CommandHandler("today", today_command))
    app.add_handler(CommandHandler("day", today_command))
    app.add_handler(CommandHandler("week", week_command))
    app.add_handler(CommandHandler("pay", pay_command))
    app.add_handler(CommandHandler("shift", pay_command))
    app.add_handler(CommandHandler("summary", summary_command))
    app.add_handler(CommandHandler("month", month_command))
    app.add_handler(CommandHandler("commands", commands_command))
    app.add_handler(CommandHandler("export", export_command))
    app.add_handler(CommandHandler("reminders", reminders_command))
    app.add_handler(CommandHandler("tasks", plan_command))
    app.add_handler(CommandHandler("todo", plan_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, plain_text_plan))

    if app.job_queue is not None:
        app.job_queue.run_repeating(reminder_job, interval=60, first=10)

    print("Bot started. Press Ctrl+C to stop.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
