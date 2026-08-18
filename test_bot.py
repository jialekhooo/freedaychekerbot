from datetime import date, timedelta
from decimal import Decimal

from bot import add_expense, add_plan, plans_for_date, set_budget, summary_text, total_expenses


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
