# dk_results

Operational tooling for DraftKings contest tracking, Google Sheets updates, and Discord
notifications (see `db_main.py:main`, `update_contests.py:check_contests_for_completion`,
`find_new_double_ups.py:main`, `bot/discord_bot.py:main`).

## Runtime Entry Points (Externally Scheduled)

Scheduling is external to this repo (cron/systemd/etc). Each entry point exposes a
`main()` and is runnable as a script or module (`db_main.py:main`,
`find_new_double_ups.py:main`, `update_contests.py:main`, `bot/discord_bot.py:main`).

- `db_main.py` updates Google Sheets for a live contest per sport by downloading salary
  and standings CSVs, constructing `Results`, and writing via `DFSSheet`
  (`db_main.py:process_sport`, `classes/draftkings.py:download_salary_csv`,
  `classes/draftkings.py:download_contest_rows`, `classes/results.py:Results`,
  `classes/dfssheet.py:DFSSheet`).
- `find_new_double_ups.py` polls the DraftKings lobby, filters double-up contests using
  sport-specific thresholds, compares against the database, inserts new contests, and
  sends Discord webhook notifications (`find_new_double_ups.py:process_sport`,
  `find_new_double_ups.py:get_double_ups`, `classes/contestdatabase.py:insert_contests`,
  `bot/webhook.py:DiscordWebhook`).
- `update_contests.py` updates contest status and `positions_paid` for entries already
  in the database and sends Discord bot notifications for warning/live/completed events,
  with de-duplication tracked in a notifications table
  (`update_contests.py:check_contests_for_completion`,
  `update_contests.py:db_update_contest`, `update_contests.py:create_notifications_table`,
  `update_contests.py:_format_contest_announcement`).
- `bot/discord_bot.py` runs a long-lived Discord bot that exposes contest lookup and
  health commands (see command handlers in `bot/discord_bot.py:contests`,
  `bot/discord_bot.py:live`, `bot/discord_bot.py:upcoming`,
  `bot/discord_bot.py:health`, `bot/discord_bot.py:sports`).

## Discord Bot Commands

The Discord bot responds to the following commands (see handler functions in
`bot/discord_bot.py`):

- `!contests <sport>` -> show a live contest for that sport (`bot/discord_bot.py:contests`)
- `!live` -> list live contests across supported sports (`bot/discord_bot.py:live`)
- `!upcoming` -> show next upcoming contest per sport (`bot/discord_bot.py:upcoming`)
- `!sports` -> list supported sports (`bot/discord_bot.py:sports`)
- `!health` -> bot and host uptime (`bot/discord_bot.py:health`)

Supported sports are derived from `Sport.__subclasses__()` in `classes/sport.py` and
used in CLI/bot choices (`classes/sport.py:Sport`, `db_main.py:main`,
`find_new_double_ups.py:main`, `bot/discord_bot.py:_sport_choices`).

## Configuration (Environment Variables)

Environment variables are read directly in code (see referenced symbols below).

| Variable | Used by | Notes |
| --- | --- | --- |
| `CONTESTS_DB_PATH` | `update_contests.py:DB_FILE`, `bot/discord_bot.py:DB_PATH` | Defaults to `contests.db` in those modules. |
| `DISCORD_NOTIFICATIONS_ENABLED` | `update_contests.py:DISCORD_NOTIFICATIONS_ENABLED` | Controls whether `update_contests.py` sends notifications. |
| `DISCORD_BOT_TOKEN` | `update_contests.py:_build_discord_sender`, `bot/discord_bot.py:BOT_TOKEN` | Required for bot-based notifications and the Discord service. |
| `DISCORD_CHANNEL_ID` | `update_contests.py:_build_discord_sender`, `bot/discord_bot.py:ALLOWED_CHANNEL_ID` | Required for bot-based notifications; also gates allowed channel. |
| `DISCORD_WEBHOOK` | `find_new_double_ups.py:main` | Enables webhook-based notifications for double-ups. |
| `SPREADSHEET_ID` | `classes/dfssheet.py:Sheet.__init__`, `update_contests.py:SPREADSHEET_ID`, `bot/discord_bot.py:SPREADSHEET_ID`, `generate_sheet_gids.py:main` | Required for Google Sheets access and sheet link generation. |
| `SHEET_GIDS_FILE` | `update_contests.py:SHEET_GIDS_FILE`, `bot/discord_bot.py:SHEET_GIDS_FILE` | Defaults to `sheet_gids.yaml` in those modules. |
| `CONTEST_WARNING_MINUTES` | `update_contests.py:CONTEST_WARNING_MINUTES` | Default warning minutes used if schedule file missing. |
| `CONTEST_WARNING_SCHEDULE_FILE` | `update_contests.py:WARNING_SCHEDULE_FILE_ENV` | Defaults to `contest_warning_schedules.yaml`. |
| `DISCORD_LOG_FILE` | `bot/discord_bot.py:DISCORD_LOG_FILE` | Optional file path for bot logs. |
| `DK_PLATFORM` | `classes/cookieservice.py:get_rookie_cookies` | Controls cookie source path behavior. |
| `COOKIES_DB_PATH` | `classes/cookieservice.py:get_rookie_cookies` | Optional Chromium cookie DB path for DK cookies. |

Both `find_new_double_ups.py` and `classes/cookieservice.py` call `dotenv.load_dotenv()`
to load environment defaults (`find_new_double_ups.py:load_dotenv`,
`classes/cookieservice.py:load_dotenv`).

## Data Files and Artifacts

- `contests.db` is the default SQLite database name, with a `contests` table created by
  `ContestDatabase.create_table()` (`classes/contestdatabase.py:ContestDatabase.create_table`)
  and a `contest_notifications` table created by `update_contests.py` for de-duplication
  (`update_contests.py:create_notifications_table`).
- `contest_warning_schedules.yaml` defines per-sport warning schedules; keys are
  normalized to lowercase and fall back to `default` (`update_contests.py:_load_warning_schedule_map`,
  `update_contests.py:_warning_schedule_for`, `contest_warning_schedules.yaml`).
- `sheet_gids.yaml` is a YAML mapping of sheet title to numeric gid; used for building
  sheet links (`update_contests.py:_load_sheet_gid_map`, `bot/discord_bot.py:_load_sheet_gid_map`).
  It can be generated via `generate_sheet_gids.py` (`generate_sheet_gids.py:main`,
  `classes/dfssheet.py:fetch_sheet_gids`).
- `client_secret.json` is required for Google Sheets service account auth
  (`classes/dfssheet.py:Sheet.setup_service`).
- `vips.yaml` is an optional list of VIP usernames used by `db_main.py`
  (`db_main.py:load_vips`).
- `salary/` and `contests/` are used to store downloaded CSVs for salary and standings
  (`db_main.py:SALARY_DIR`, `db_main.py:CONTEST_DIR`,
  `classes/draftkings.py:download_salary_csv`,
  `classes/draftkings.py:download_contest_rows`).

## Contest Warning Schedules

`update_contests.py` loads a per-sport warning schedule from
`CONTEST_WARNING_SCHEDULE_FILE` and falls back to `CONTEST_WARNING_MINUTES` when needed
(`update_contests.py:_load_warning_schedule_map`,
`update_contests.py:_warning_schedule_for`, `update_contests.py:CONTEST_WARNING_MINUTES`).

The warning logic compares the next upcoming contest start time to `now` plus each
warning window, so periodic execution is expected (see the window check in
`update_contests.py:check_contests_for_completion`).

Default schedule file contents (from `contest_warning_schedules.yaml`):

```yaml
default: [25]
```

## Logging

Logging is configured via `logging.ini` and loaded by most modules using
`logging.config.fileConfig()` (`update_contests.py`, `db_main.py`,
`classes/contestdatabase.py`, `classes/dfssheet.py`).
