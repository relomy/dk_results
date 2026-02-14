# dk_results

Operational tooling for DraftKings contest tracking, Google Sheets updates, and Discord
notifications (see `db_main.py:main`, `update_contests.py:check_contests_for_completion`,
`find_new_double_ups.py:main`, `bot/discord_bot.py:main`).

## Shared Infrastructure

- Google Sheets + Discord primitives are provided by `dfs_common`.
- Local development expects `dfs_common` as a sibling directory (see `pyproject.toml:[tool.uv.sources]`).

## Sheet Service

Construct the sheet service with the repo helper so entry points only need one import:

```python
from classes.sheets_service import build_dfs_sheet_service

sheet = build_dfs_sheet_service("NBA")
```

## Runtime Entry Points (Externally Scheduled)

Scheduling is external to this repo (cron/systemd/etc). Each entry point exposes a
`main()` and is runnable as a script or module (`db_main.py:main`,
`find_new_double_ups.py:main`, `update_contests.py:main`, `bot/discord_bot.py:main`).

## Export Fixture Snapshot

Use the unified CLI to export a deterministic, decision-ready JSON snapshot for one contest:

```bash
uv run python export_fixture.py --sport NBA --out fixtures/nba-primary-live-fixture.json
```

Optional explicit contest:

```bash
uv run python export_fixture.py --sport NBA --contest-id 123456789 --out fixtures/nba-123456789-fixture.json
```

Multi-sport bundle for testing with explicit IDs:

```bash
uv run python export_fixture.py bundle --item NBA:188080404 --item GOLF:187937165 --out /tmp/dk-two-sport-bundle.json
```

Notes:
- The exporter reuses the same `dk_results` data sources/endpoints already in use (contest DB + existing `Draftkings` client methods); no new scraping endpoints are introduced.
- Contest selection is deterministic and includes a `selection.reason` object plus compact candidate summary for transparency.
- Output is byte-stable for tests (`sort_keys`, fixed separators, stable ordering) and keeps major sections present with explicit `null` where data is unavailable.
- Cookies/auth handling follows existing project mechanisms (`classes/dksession.py`, `pickled_cookies_works.txt`); no credentials are printed in logs.

Optional `db_main.py` addendum export for integration testing:

```bash
uv run python db_main.py --sport NBA GOLF --snapshot-out /tmp/live-snapshot.json
```

`--snapshot-out` is opt-in and does not change normal sheet-writing behavior when omitted.

- `db_main.py` updates Google Sheets for a live contest per sport by downloading salary
  and standings CSVs, constructing `Results`, and writing via `DfsSheetService`
  (`db_main.py:process_sport`, `classes/draftkings.py:download_salary_csv`,
  `classes/draftkings.py:download_contest_rows`, `classes/results.py:Results`,
  `classes/dfs_sheet_service.py:DfsSheetService`).
- `find_new_double_ups.py` polls the DraftKings lobby, filters double-up contests using
  sport-specific thresholds, compares against the database, inserts new contests, and
  sends Discord webhook notifications (`find_new_double_ups.py:process_sport`,
  `find_new_double_ups.py:get_double_ups`, `classes/contestdatabase.py:insert_contests`,
  `dfs_common/discord.py:WebhookSender`).
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

Sample config files are provided to copy/adapt:
`.env.example`, `client_secret.json.sample`, `sheet_gids.yaml.sample`,
`vips.yaml.sample` (see files in repo root).

| Variable                        | Used by                                                                                                                                                      | Notes                                                             |
| ------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------- |
| `DFS_STATE_DIR`                 | `dfs_common.state.contests_db_path`, `update_contests.py:_contests_db_path`, `bot/discord_bot.py:_db_path`                                                 | Required. Shared state directory containing `contests.db`.        |
| `DISCORD_NOTIFICATIONS_ENABLED` | `update_contests.py:DISCORD_NOTIFICATIONS_ENABLED`                                                                                                           | Controls whether `update_contests.py` sends notifications.        |
| `DISCORD_BOT_TOKEN`             | `update_contests.py:_build_discord_sender`, `bot/discord_bot.py:BOT_TOKEN`                                                                                   | Required for bot-based notifications and the Discord service.     |
| `DISCORD_CHANNEL_ID`            | `update_contests.py:_build_discord_sender`, `bot/discord_bot.py:ALLOWED_CHANNEL_ID`                                                                          | Required for bot-based notifications; also gates allowed channel. |
| `DISCORD_WEBHOOK`               | `find_new_double_ups.py:main`                                                                                                                                | Enables webhook-based notifications for double-ups.               |
| `SPREADSHEET_ID`                | `classes/sheets_service.py:build_dfs_sheet_service`, `update_contests.py:SPREADSHEET_ID`, `bot/discord_bot.py:SPREADSHEET_ID`, `generate_sheet_gids.py:main` | Required for Google Sheets access and sheet link generation.      |
| `SHEET_GIDS_FILE`               | `update_contests.py:SHEET_GIDS_FILE`, `bot/discord_bot.py:SHEET_GIDS_FILE`                                                                                   | Defaults to `sheet_gids.yaml` in those modules.                   |
| `CONTEST_WARNING_MINUTES`       | `update_contests.py:CONTEST_WARNING_MINUTES`                                                                                                                 | Default warning minutes used if schedule file missing.            |
| `CONTEST_WARNING_SCHEDULE_FILE` | `update_contests.py:WARNING_SCHEDULE_FILE_ENV`                                                                                                               | Defaults to `contest_warning_schedules.yaml`.                     |
| `DISCORD_LOG_FILE`              | `bot/discord_bot.py:DISCORD_LOG_FILE`                                                                                                                        | Optional file path for bot logs.                                  |
| `DK_PLATFORM`                   | `classes/cookieservice.py:get_rookie_cookies`                                                                                                                | Controls cookie source path behavior.                             |
| `COOKIES_DB_PATH`               | `classes/cookieservice.py:get_rookie_cookies`                                                                                                                | Optional Chromium cookie DB path for DK cookies.                  |

Both `find_new_double_ups.py` and `classes/cookieservice.py` call `dotenv.load_dotenv()`
to load environment defaults (`find_new_double_ups.py:load_dotenv`,
`classes/cookieservice.py:load_dotenv`).

Google Sheets access uses the shared `dfs_common` helpers that expect a
`client_secret.json` service account file located in the repository root. The guard in
`dfs_common.sheets.service_account_provider` raises immediately if that file is missing,
so place the credential file at the repo root before running `db_main.py` or the other writers.

## Data Files and Artifacts

- `contests.db` lives under `DFS_STATE_DIR` and stores shared contest state.
  The `contests` table schema is managed by `dfs_common` via `dfs_common.contests.init_schema`,
  and `contest_notifications` is created by `update_contests.py` for de-duplication
  (`update_contests.py:create_notifications_table`).
- Sample config templates live alongside the real files and are safe to share:
  `client_secret.json.sample`, `sheet_gids.yaml.sample`, and `vips.yaml.sample`.
- `contest_warning_schedules.yaml` defines per-sport warning schedules; keys are
  normalized to lowercase and fall back to `default` (`update_contests.py:_load_warning_schedule_map`,
  `update_contests.py:_warning_schedule_for`, `contest_warning_schedules.yaml`).
- `sheet_gids.yaml` is a YAML mapping of sheet title to numeric gid; used for building
  sheet links (`update_contests.py:_load_sheet_gid_map`, `bot/discord_bot.py:_load_sheet_gid_map`).
  It can be generated via `generate_sheet_gids.py` (`generate_sheet_gids.py:main`,
  `classes/sheets_service.py:fetch_sheet_gids`).
- `client_secret.json` is required for Google Sheets service account auth
  (`classes/sheets_service.py:build_dfs_sheet_service`).
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
`classes/contestdatabase.py`, `classes/dfs_sheet_service.py`).
