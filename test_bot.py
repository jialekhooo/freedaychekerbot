from datetime import date, datetime, timedelta
from decimal import Decimal

from bot import (
    add_plan,
    add_shift,
    build_agenda_message,
    build_month_summary,
    build_shifts_csv,
    get_default_rate,
    get_reminder_settings,
    parse_clock_time,
    parse_month_string,
    parse_shift_text,
    plans_for_date,
    plans_starting_soon,
    set_default_rate,
    set_reminder_time,
    summary_text,
    total_pay,
)


def make_state():
    return {"shifts": [], "plans": [], "default_rate": None}


def test_parse_shift_text_computes_rate_date_and_location():
    parsed = parse_shift_text("13/8 8am-8pm 15/h Wedding gig @ Marina Bay Sands", default_rate=None)

    assert parsed["date"] == "2026-08-13"
    assert parsed["start_hm"] == (8, 0)
    assert parsed["end_hm"] == (20, 0)
    assert parsed["rate"] == Decimal("15")
    assert parsed["name"] == "Wedding gig"
    assert parsed["location"] == "Marina Bay Sands"


def test_parse_shift_text_falls_back_to_default_rate():
    parsed = parse_shift_text("today 9am-5pm Roadshow", default_rate=Decimal("20"))

    assert parsed["rate"] == Decimal("20")


def test_add_shift_computes_hours_and_pay():
    state = make_state()
    parsed = parse_shift_text("13/8 8am-8pm 15/h Wedding gig", default_rate=None)

    shift = add_shift(state, parsed)

    assert shift["hours"] == "12"
    assert shift["pay"] == "180.00"
    assert total_pay(state) == Decimal("180.00")


def test_add_shift_handles_overnight_range():
    state = make_state()
    parsed = parse_shift_text("today 10pm-2am 10/h Night shift", default_rate=None)

    shift = add_shift(state, parsed)

    assert shift["hours"] == "4"
    assert shift["pay"] == "40.00"


def test_default_rate_get_and_set():
    state = make_state()
    assert get_default_rate(state) is None

    set_default_rate(state, Decimal("18"))

    assert get_default_rate(state) == Decimal("18")


def test_combined_summary_and_plan_logic():
    state = make_state()
    parsed = parse_shift_text("today 2pm-6pm 15/h Event", default_rate=None)
    add_shift(state, parsed)
    add_plan(state, "today 2pm-3pm finish report")

    summary = summary_text(state, "today")

    assert "This month's pay: $60.00" in summary
    assert "Planned today: 1 open, 0 done" in summary


def test_recurring_daily_plan_shows_on_future_dates():
    state = make_state()

    add_plan(state, "today 8am every day gym")
    future_day = (date.today() + timedelta(days=3)).isoformat()

    matches = plans_for_date(state, future_day)

    assert len(matches) == 1
    assert matches[0]["repeat"] == "daily"


def test_parse_clock_time_variants():
    assert parse_clock_time("2pm") == (14, 0)
    assert parse_clock_time("14:30") == (14, 30)
    assert parse_clock_time("9am") == (9, 0)
    assert parse_clock_time("not-a-time") is None


def test_plans_starting_soon_within_window():
    now = datetime(2026, 8, 18, 8, 45)
    plans = [
        {"id": 1, "done": False, "start_time": "9:00"},
        {"id": 2, "done": False, "start_time": "11:00"},
        {"id": 3, "done": True, "start_time": "9:05"},
    ]

    due = plans_starting_soon(plans, now)

    assert [p["id"] for p in due] == [1]


def test_reminder_settings_defaults_and_update():
    state = make_state()

    cfg = get_reminder_settings(state, 42)
    assert cfg["enabled"] is False
    assert cfg["time"] == "08:00"

    set_reminder_time(state, 42, "07:30", tz_offset=5)
    updated = get_reminder_settings(state, 42)
    assert updated["enabled"] is True
    assert updated["time"] == "07:30"
    assert updated["tz_offset"] == 5


def test_build_agenda_message_and_csv_export():
    state = make_state()
    parsed = parse_shift_text("today 9am-5pm 12/h Bus shift", default_rate=None)
    shift = add_shift(state, parsed)
    plan = add_plan(state, "today 9am gym")

    agenda = build_agenda_message([plan])
    csv_text = build_shifts_csv(state)

    assert "gym" in agenda
    assert "Bus shift" in csv_text
    assert shift["pay"] in csv_text


def test_parse_month_string_variants():
    today = date.today()
    assert parse_month_string(None) == (today.year, today.month)
    assert parse_month_string("2026-08") == (2026, 8)
    assert parse_month_string("aug") == (today.year, 8)
    assert parse_month_string("August 2025") == (2025, 8)


def test_build_month_summary_totals_pay_and_hours():
    state = make_state()
    add_shift(state, parse_shift_text("5/8 9am-5pm 15/h Shift one", default_rate=None))
    add_shift(state, parse_shift_text("10/8 6pm-10pm 20/h Shift two", default_rate=None))
    add_shift(state, parse_shift_text("1/7 9am-5pm 15/h Out of month", default_rate=None))

    summary = build_month_summary(state, 2026, 8)

    assert "August 2026" in summary
    assert "$200.00" in summary
    assert "12h" in summary
    assert "2 shifts" in summary

