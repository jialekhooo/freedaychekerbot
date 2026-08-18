# Daily Pay Tracker Bot

A Telegram bot that combines daily task planning with personal pay tracking in one place.

## Features

- Track expenses and income, with per-category budgets
- Review spending totals and recent entries
- Add, complete, and list daily plans (one-off or recurring)
- Quick-add a plan by just sending a plain message, no command needed
- `/today` and `/week` views of upcoming plans
- `/month` spending breakdown by category
- CSV export of expenses
- Daily agenda + per-plan heads-up reminders
- See a quick summary of both finance and plan status

## Setup

1. Create a virtual environment:
   python -m venv .venv
2. Activate it:
   - Windows PowerShell: .\.venv\Scripts\Activate.ps1
   - Windows CMD: .\.venv\Scripts\activate.bat
3. Install dependencies:
   pip install -r requirements.txt
4. Copy `.env.example` to `.env` and set your Telegram bot token.
5. Run the bot:
   python bot.py

## Commands

- `/start` / `/help` - Show bot welcome screen
- `/commands` - Full command reference
- Plain message (no command) - quick-add a plan, e.g. `fri 3pm dentist`
- `/plan add today 2pm-4pm finish report` - Add a plan
- `/plan add every mon 9am gym` - Add a recurring plan
- `/plan list` - List all plans
- `/plan done 1` - Mark a plan done
- `/plan delete 1` - Remove a plan
- `/today` - Today's plans
- `/week` - Next 7 days of plans
- `/pay add 25 food groceries` - Add an expense
- `/pay list` / `/pay total` / `/pay delete 1`
- `/income add 600 salary monthly` - Log income
- `/budget set groceries 250` - Set a budget
- `/month [aug|2026-08|last month]` - Monthly spending by category
- `/export` - CSV export of expenses
- `/reminders on|off|07:30 [+8]` - Daily agenda + heads-up before plans
- `/summary` - Combined money + plan overview

## Hosting on Fly.io

The bot runs as a long-polling background worker (no HTTP service needed) with a persistent volume for `data/storage.json`.

```
fly launch --no-deploy --copy-config --name <your-app-name> --region sin
fly volumes create bot_data --region sin --size 1 --app <your-app-name>
fly secrets set TELEGRAM_BOT_TOKEN=<your-token> --app <your-app-name>
fly deploy --app <your-app-name>
```

`fly.toml` sets `BOT_DATA_DIR=/data`, mounted from the `bot_data` volume, so expenses/plans survive redeploys. Check logs with `fly logs --app <your-app-name>`.

## Notes

- Data is stored in `data/storage.json` locally, or `/data/storage.json` when `BOT_DATA_DIR` is set (e.g. on Fly.io).
- The bot expects a token from BotFather in the environment variable `TELEGRAM_BOT_TOKEN`.
