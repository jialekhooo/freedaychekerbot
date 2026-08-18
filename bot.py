import csv
import io
import json
import os
import re
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

DATA_DIR = Path(__file__).resolve().parent / "data"
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
    DATA_DIR.mkdir(exist_ok=True)
    if not DATA_FILE.exists():
        DATA_FILE.write_text(
            json.dumps({"expenses": [], "plans": [], "budgets": {}, "incomes": []}, indent=2),
            encoding="utf-8",
        )


def load_state() -> dict:
    ensure_storage()
    try:
        with DATA_FILE.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (json.JSONDecodeError, OSError):
        data = {"expenses": [], "plans": [], "budgets": {}, "incomes": []}

    data.setdefault("expenses", [])
    data.setdefault("plans", [])
    data.setdefault("budgets", {})
    data.setdefault("incomes", [])
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

    for fmt in ("%d/%m/%Y", "%d/%m", "%d-%m-%Y", "%d-%m", "%Y-%m-%d"):
        try:
            return datetime.strptime(value.strip(), fmt).date()
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


def add_expense(state: dict, amount: Decimal, category: str, note: str, expense_date: str | None = None) -> dict:
    expense_id = len(state["expenses"]) + 1
    state["expenses"].append(
        {
            "id": expense_id,
            "amount": str(amount),
            "category": category.lower(),
            "note": note,
            "date": expense_date or date.today().isoformat(),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    return state


def add_income(state: dict, amount: Decimal, source: str, note: str = "") -> dict:
    income_id = len(state["incomes"]) + 1
    state["incomes"].append(
        {
            "id": income_id,
            "amount": str(amount),
            "source": source,
            "note": note,
            "date": date.today().isoformat(),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    return state


def set_budget(state: dict, category: str, amount: Decimal) -> None:
    state["budgets"][category.lower()] = str(amount)


def total_expenses(state: dict) -> Decimal:
    return sum((Decimal(item["amount"]) for item in state["expenses"]), Decimal("0"))


def total_income(state: dict) -> Decimal:
    return sum((Decimal(item["amount"]) for item in state["incomes"]), Decimal("0"))


def category_totals(state: dict) -> dict:
    totals = defaultdict(Decimal)
    for item in state["expenses"]:
        totals[item["category"].lower()] += Decimal(item["amount"])
    return dict(totals)


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


def expenses_for_month(state: dict, year: int, month: int) -> list:
    prefix = f"{year:04d}-{month:02d}"
    return [item for item in state["expenses"] if item["date"].startswith(prefix)]


def build_month_summary(state: dict, year: int, month: int) -> str:
    expenses = expenses_for_month(state, year, month)
    label = date(year, month, 1).strftime("%B %Y")
    if not expenses:
        return f"No expenses logged for {label}."

    total = sum((Decimal(item["amount"]) for item in expenses), Decimal("0"))
    totals = defaultdict(Decimal)
    for item in expenses:
        totals[item["category"].lower()] += Decimal(item["amount"])

    lines = [f"{label} spending: {format_currency(total)}", "By category:"]
    for category, amount in sorted(totals.items(), key=lambda kv: kv[1], reverse=True):
        lines.append(f"- {category.title()}: {format_currency(amount)}")
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


def build_expenses_csv(state: dict) -> str:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["id", "date", "amount", "category", "note"])
    for item in state["expenses"]:
        writer.writerow([item["id"], item["date"], item["amount"], item["category"], item["note"]])
    return output.getvalue()


def summary_text(state: dict, target_date: str | None = None) -> str:
    today_value = parse_date_string(target_date).isoformat() if target_date else date.today().isoformat()
    expense_total = total_expenses(state)
    income_total = total_income(state)
    net = income_total - expense_total
    open_today = sum(1 for item in plans_for_date(state, today_value) if not item["done"])
    done_today = sum(1 for item in plans_for_date(state, today_value) if item["done"])
    all_open = sum(1 for item in state["plans"] if not item["done"])
    budget_lines = []
    for category, limit in state.get("budgets", {}).items():
        spent = category_totals(state).get(category, Decimal("0"))
        remaining = Decimal(limit) - spent
        budget_lines.append(f"- {category.title()}: {format_currency(spent)} / {format_currency(Decimal(limit))} left {format_currency(remaining)}")

    budget_block = "\n".join(budget_lines) if budget_lines else "- No budgets set yet. Use /budget set groceries 250"
    return (
        "Daily overview:\n"
        f"- Net cash: {format_currency(net)}\n"
        f"- Expenses: {format_currency(expense_total)}\n"
        f"- Income: {format_currency(income_total)}\n"
        f"- Planned today: {open_today} open, {done_today} done\n"
        f"- All open plans: {all_open}\n"
        "- Budgets:\n"
        f"{budget_block}"
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
        "Welcome to your money + daily planner bot.\n\n"
        "Just send a plain message like 'tomorrow 4pm gym' to add a plan - no command needed.\n\n"
        "Core commands:\n"
        "- /plan add today 2pm-4pm finish report\n"
        "- /plan add every mon 9am gym (recurring)\n"
        "- /plan list\n"
        "- /plan done 1\n"
        "- /today\n"
        "- /week\n"
        "- /pay add 25 food groceries\n"
        "- /pay total\n"
        "- /budget set groceries 250\n"
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
        "/pay add <amount> <category> <note> - log an expense",
        "/pay list - recent expenses",
        "/pay total - total spending",
        "/pay delete <id> - remove an expense",
        "/income add <amount> <source> [note] - log income",
        "/income list - recent income",
        "/budget set <category> <amount> - set a budget",
        "/budget list - show budgets vs spending",
        "/month [aug|2026-08|last month] - monthly spending by category",
        "/export - CSV export of expenses",
        "/reminders on|off|07:30 [+8] - daily agenda + heads-up before plans",
        "/summary - daily overview of money + plans",
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
        message = "Today is clear.\n- No plans scheduled.\n- Spend total: " + format_currency(total_expenses(state))
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
            "- /pay add 25 food groceries\n"
            "- /pay list\n"
            "- /pay total\n"
            "- /pay delete 1\n"
            "- /income add 600 salary monthly"
        )
        return

    action = args[0].lower()

    if action == "add":
        if len(args) < 4:
            await update.message.reply_text("Usage: /pay add 25 food groceries")
            return
        try:
            amount = Decimal(args[1])
        except InvalidOperation:
            await update.message.reply_text("Amount must be a valid number, e.g. 25 or 14.75")
            return
        category = args[2]
        note = " ".join(args[3:])
        add_expense(state, amount, category, note)
        save_state(state)
        await update.message.reply_text(f"Added expense: {format_currency(amount)} for {category} - {note}")
        return

    if action == "list":
        expenses = state["expenses"]
        if not expenses:
            await update.message.reply_text("No expenses logged yet.")
            return
        lines = ["Recent expenses:"]
        for item in reversed(expenses):
            lines.append(f"#{item['id']} {item['date']} {format_currency(Decimal(item['amount']))} | {item['category']} | {item['note']}")
        await update.message.reply_text("\n".join(lines))
        return

    if action == "total":
        await update.message.reply_text(f"Total spending: {format_currency(total_expenses(state))}")
        return

    if action == "delete":
        if len(args) < 2:
            await update.message.reply_text("Usage: /pay delete 1")
            return
        try:
            expense_id = int(args[1])
        except ValueError:
            await update.message.reply_text("Expense ID must be a number.")
            return
        remaining = [item for item in state["expenses"] if item["id"] != expense_id]
        if len(remaining) == len(state["expenses"]):
            await update.message.reply_text(f"No expense found with ID {expense_id}.")
            return
        state["expenses"] = remaining
        save_state(state)
        await update.message.reply_text(f"Removed expense #{expense_id}.")
        return

    await update.message.reply_text("Unknown pay command. Try /pay add, /pay list, /pay total or /pay delete.")


async def income_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    state = load_state()
    args = context.args
    if not args:
        await update.message.reply_text("Usage: /income add 600 salary monthly")
        return
    action = args[0].lower()
    if action == "add":
        if len(args) < 3:
            await update.message.reply_text("Usage: /income add 600 salary monthly")
            return
        try:
            amount = Decimal(args[1])
        except InvalidOperation:
            await update.message.reply_text("Income amount must be a valid number.")
            return
        source = args[2]
        note = " ".join(args[3:]) if len(args) > 3 else ""
        add_income(state, amount, source, note)
        save_state(state)
        await update.message.reply_text(f"Added income: {format_currency(amount)} from {source}")
        return
    if action == "list":
        incomes = state["incomes"]
        if not incomes:
            await update.message.reply_text("No income logged yet.")
            return
        lines = ["Income records:"]
        for item in reversed(incomes):
            lines.append(f"#{item['id']} {item['date']} {format_currency(Decimal(item['amount']))} | {item['source']} | {item['note']}")
        await update.message.reply_text("\n".join(lines))
        return
    await update.message.reply_text("Unknown income command. Try /income add or /income list.")


async def budget_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    state = load_state()
    args = context.args
    if not args:
        await update.message.reply_text("Usage:\n- /budget set groceries 250\n- /budget list")
        return

    action = args[0].lower()
    if action == "set":
        if len(args) < 3:
            await update.message.reply_text("Usage: /budget set groceries 250")
            return
        category = args[1]
        try:
            amount = Decimal(args[2])
        except InvalidOperation:
            await update.message.reply_text("Budget amount must be a valid number.")
            return
        set_budget(state, category, amount)
        save_state(state)
        await update.message.reply_text(f"Set budget for {category}: {format_currency(amount)}")
        return

    if action == "list":
        budgets = state.get("budgets", {})
        if not budgets:
            await update.message.reply_text("No budgets tracked yet.")
            return
        lines = ["Budgets:"]
        totals = category_totals(state)
        for name, limit in budgets.items():
            spent = totals.get(name, Decimal("0"))
            remaining = Decimal(limit) - spent
            lines.append(f"- {name.title()}: {format_currency(spent)} / {format_currency(Decimal(limit))} (left {format_currency(remaining)})")
        await update.message.reply_text("\n".join(lines))
        return

    await update.message.reply_text("Unknown budget command. Try /budget set or /budget list.")


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
    if not state["expenses"]:
        await update.message.reply_text("No expenses to export yet.")
        return
    csv_text = build_expenses_csv(state)
    buffer = io.BytesIO(csv_text.encode("utf-8"))
    buffer.name = "expenses.csv"
    await update.message.reply_document(document=buffer, filename="expenses.csv", caption="Expense export")


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
    app.add_handler(CommandHandler("expense", pay_command))
    app.add_handler(CommandHandler("income", income_command))
    app.add_handler(CommandHandler("budget", budget_command))
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
