from datetime import date, datetime, timedelta
from decimal import Decimal

from bot import (
    add_expense,
    add_plan,
    build_agenda_message,
    build_expenses_csv,
    build_month_summary,
    get_reminder_settings,
    parse_clock_time,
    parse_month_string,
    plans_for_date,
    plans_starting_soon,
    set_budget,
    set_reminder_time,
    summary_text,
    total_expenses,
)


def test_combined_summary_and_budget_logic():
    state = {"expenses": [], "plans": [], "budgets": {}, "incomes": []}

    add_expense(state, 25.5, "food", "groceries")
    add_plan(state, "today 2pm-3pm finish report")
    set_budget(state, "food", Decimal("100"))

    total = total_expenses(state)
    summary = summary_text(state, "today")

    assert total == Decimal("25.5")
    assert "Expenses: $25.50" in summary
    assert "Planned today: 1 open, 0 done" in summary
    assert "food" in summary.lower()


def test_recurring_daily_plan_shows_on_future_dates():
    state = {"expenses": [], "plans": [], "budgets": {}, "incomes": []}

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
    state = {"expenses": [], "plans": [], "budgets": {}, "incomes": []}

    cfg = get_reminder_settings(state, 42)
    assert cfg["enabled"] is False
    assert cfg["time"] == "08:00"

    set_reminder_time(state, 42, "07:30", tz_offset=5)
    updated = get_reminder_settings(state, 42)
    assert updated["enabled"] is True
    assert updated["time"] == "07:30"
    assert updated["tz_offset"] == 5


def test_build_agenda_message_and_csv_export():
    state = {"expenses": [], "plans": [], "budgets": {}, "incomes": []}
    add_expense(state, 12, "transport", "bus")
    plan = add_plan(state, "today 9am gym")

    agenda = build_agenda_message([plan])
    csv_text = build_expenses_csv(state)

    assert "gym" in agenda
    assert "transport" in csv_text
    assert "12" in csv_text


def test_parse_month_string_variants():
    today = date.today()
    assert parse_month_string(None) == (today.year, today.month)
    assert parse_month_string("2026-08") == (2026, 8)
    assert parse_month_string("aug") == (today.year, 8)
    assert parse_month_string("August 2025") == (2025, 8)


def test_build_month_summary_groups_by_category():
    state = {"expenses": [], "plans": [], "budgets": {}, "incomes": []}
    add_expense(state, 20, "food", "lunch", expense_date="2026-08-05")
    add_expense(state, 30, "food", "dinner", expense_date="2026-08-10")
    add_expense(state, 15, "transport", "bus", expense_date="2026-08-12")
    add_expense(state, 99, "food", "out of month", expense_date="2026-07-01")

    summary = build_month_summary(state, 2026, 8)

    assert "August 2026" in summary
    assert "$65.00" in summary
    assert "Food: $50.00" in summary
    assert "Transport: $15.00" in summary
