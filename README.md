# Daily Pay Tracker Bot

A Telegram bot that combines daily task planning with personal pay tracking in one place.

## Features

- Track expenses and income, with per-category budgets
- Review spending totals and recent entries
- Add, complete, and list daily plans (one-off or recurring)
- `/today` and `/week` views of upcoming plans
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
- `/export` - CSV export of expenses
- `/reminders on|off|07:30 [+8]` - Daily agenda + heads-up before plans
- `/summary` - Combined money + plan overview

## Notes

- Data is stored in `data/storage.json`.
- The bot expects a token from BotFather in the environment variable `TELEGRAM_BOT_TOKEN`.
