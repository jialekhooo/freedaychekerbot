# Daily Pay Tracker Bot

A Telegram bot that combines daily task planning with shift-based pay tracking in one place.

## Features

- Log shifts (date, time range, hourly rate, event name, location) and get computed pay automatically
- Set a default hourly rate so you don't need to repeat it every time
- Overnight shifts (e.g. `10pm-2am`) are handled correctly
- Add, complete, and list daily plans (one-off or recurring)
- Quick-add a plan by just sending a plain message, no command needed
- `/today` and `/week` views of upcoming plans
- `/month` pay breakdown with total hours and shift count
- CSV export of shifts
- Daily agenda + per-plan heads-up reminders
- See a quick summary of both pay and plan status

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
- `/pay add 13/8 8.30am-8pm 15/h Wedding gig @ Marina Bay Sands` - Log a shift
- `/pay list` - Recent shifts
- `/pay total [month]` - Total pay for a month (default: this month)
- `/pay rate 15` - Set your default hourly rate
- `/pay delete 1` - Remove a shift
- `/month [aug|2026-08|last month]` - Monthly pay breakdown
- `/export` - CSV export of shifts
- `/reminders on|off|07:30 [+8]` - Daily agenda + heads-up before plans
- `/summary` - Combined pay + plan overview

## Hosting on Fly.io

The bot runs as a long-polling background worker (no HTTP service needed) with a persistent volume for `data/storage.json`.

```
fly launch --no-deploy --copy-config --name <your-app-name> --region sin
fly volumes create bot_data --region sin --size 1 --app <your-app-name>
fly secrets set TELEGRAM_BOT_TOKEN=<your-token> --app <your-app-name>
fly deploy --app <your-app-name>
```

`fly.toml` sets `BOT_DATA_DIR=/data`, mounted from the `bot_data` volume, so shifts/plans survive redeploys. Check logs with `fly logs --app <your-app-name>`.

## Notes

- Data is stored in `data/storage.json` locally, or `/data/storage.json` when `BOT_DATA_DIR` is set (e.g. on Fly.io).
- The bot expects a token from BotFather in the environment variable `TELEGRAM_BOT_TOKEN`.
