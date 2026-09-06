# dk_results — Module Inventory

A survey of the codebase through the lens of the **codebase-design** skill: a
*module* is anything with an interface and an implementation; we care about
**depth** (behaviour behind a small interface), **seams** (where behaviour can be
swapped without editing in place), **adapters** (concrete things at a seam),
**leverage** (what callers gain), and **locality** (where change concentrates).

See `docs/CONTEXT.md` for the shared vocabulary and the canonical entries for
`Draft Group Filter`, `ContestStandings`, and `SportProcessor`.

## Architecture at a glance

```
Root shims (dkcontests.py, db_main.py, …)      thin sys.path adapters → cli.*
  └─ cli/            argument parsing + wiring  (adapters over deep modules)
  └─ sport_processor.py  ORCHESTRATOR      (SportProcessor.run)
            ├─ DkPort  ──── draftkings/client.py + session.py + cookies.py
            ├─ SheetPort ── sheets/dfs_sheet_service → repository → dfs_common
            └─ BonusSenderPort ── bot/discord_rest, dfs_common WebhookSender
  Domain (pure): sport, player, user, contest, lineup, contest_standings,
                 bonus_rules, dfs_sheet_domain
  Lobby pkg:     fetch → parsing → draft_group_filter → contest_filter →
                 double_ups → formatting
  Analytics:     optimizer (LP), trainfinder (clustering)
  Snapshot:      services/snapshot_v3, commands/export_fixture, vip_lineups
  Bot:           bot/discord_bot, discord_rest, botinterface
  Cross-cutting: config, logging, paths, discord_roles
```

The dependency arrows point downward toward pure, dependency-light modules. The
three `Protocol` ports in `sport_processor.py` and `DkHttpPort` in
`vip_lineups.py` are the load-bearing **seams** that keep the orchestrator
testable and the HTTP/Sheets/Discord edges substitutable.

---

## 1. Orchestration

### SportProcessor — `sport_processor.py` *(deep, canonical in CONTEXT.md)*
The workflow spine. `SportProcessor.run(sport_name, sport_cls) -> int` hides the
entire "find live contest → download rows → parse standings → compute analytics
→ write sheet → announce bonuses" pipeline behind one call.
- **Seams / adapters:** `DkPort` (DraftKings HTTP), `SheetPort` (Google Sheets,
  built via injected `sheet_factory: Callable[[str], SheetPort]`),
  `BonusSenderPort` (Discord). `ContestDatabase` injected directly.
- **Interface also includes** its error modes as control flow:
  `NoLiveContestError`, `StandingsUnavailableError`, `StandsParseError` signal
  "skip this sport"; `SportProcessorConfig` (frozen) carries filesystem/limit config.
- **Depth:** high — the biggest leverage-per-interface unit in the repo.

### Snapshot v3 — `services/snapshot_v3/`
Collects current DraftKings data, derives analytics, and builds the deterministic
schema-3 JSON envelope consumed by downstream systems. The package is split into
collection, derivation, contract building, normalization, validation, and stable
serialization seams. Its public orchestration surface is
`pipeline.build_snapshot_v3_envelope`.
- **Collection split:** `collector.py` keeps IO and contest selection at the
  boundary; `sections.py` holds the pure per-section builders
  (`build_standings_rows`, `build_players`, `build_top_remaining_players`,
  `build_watchlist`, `build_cash_line`, `build_train_clusters`) that turn a parsed
  `ContestStandings` into snapshot sections, so the collector reads as an
  IO → parse → delegate → assemble orchestrator.
- **Depth:** high — the package keeps external collection at the boundary and
  exposes one schema-3 generation path.

### VIP Lineups — `vip_lineups.py`
`fetch_vip_lineups(...)` gathers VIP entries and parses their scorecards into
`VipLineup`/`VipPlayer` value objects. Seam: `DkHttpPort` protocol so the DK
fetch is injectable. `load_vips()` and `build_vip_entries()` round out the interface.

---

## 2. Domain (pure, dependency-light)

| Module | Interface | Depth / role |
|---|---|---|
| `domain/sport.py` | `Sport` base + ~22 sport subclasses; registry fns `iter_sports`, `get_sport_choices`, `get_sport`, `require_sport`, `get_lineup_range` | Deep: a large sport taxonomy behind small lookup fns. **Seam:** registry is *discovered dynamically* from subclasses (`_build_sport_registry`) — read-only `Mapping`. |
| `domain/contest_standings.py` | `parse_contest_standings(salary_rows, standings_rows, …) -> ContestStandings`; `players_to_values` | Deep pure parser (canonical in CONTEXT.md). Contest metadata stays with callers. |
| `domain/lineup.py` | `parse_lineup_string`, `Lineup`, `LockedSlot`, `normalize_name`, `LineupParseError` | Parsing + value object; validates roster slots. |
| `domain/player.py` | `Player` | Athlete value object, per-sport aware. |
| `domain/user.py` | `User` | DK user value object. |
| `domain/contest.py` | `Contest` (from JSON) + `get_dt_from_timestamp` | Contest value object. |
| `domain/bonus_rules.py` | `parse_bonus_counts(sport, stats_description)` | Pure per-sport parsing rules (golf/nba/mlb/soc). |
| `domain/dfs_sheet_domain.py` | `end_col_for_sport`, `data/header/lineup_range_for_sport`, `build_values_for_vip_lineup` | Pure sheet-range + value formatting; no I/O. |

---

## 3. DraftKings access tier

| Module | Interface | Role |
|---|---|---|
| `draftkings/client.py` | `DraftKings`: `get_leaderboard`, `get_contest_detail`, `get_lobby_contests`, `get_entry`, `get_contest_entrants_page`, `download_contest_rows`, `download_salary_csv`, `clone_auth_to` | Deep HTTP client — the concrete **`DkPort` adapter**. |
| `draftkings/session.py` | `AuthSession`: `get_session`, `setup_session`, `cj_from_pickle` | Authenticated `requests.Session` construction. |
| `draftkings/cookies.py` | `get_dk_cookies`, `get_browser_cookies`, `cookies_to_dict/_jar`, `load/save_cookies_to_pickle` | Cookie acquisition/persistence seam under AuthSession. |

---

## 4. Google Sheets tier

| Module | Interface | Role |
|---|---|---|
| `sheets/dfs_sheet_service.py` | `DfsSheetService`: `clear_standings/lineups`, `write_players/column(s)`, `add_contest_details/last_updated/min_cash/non_cashing_info/train_info/optimal_lineup`, `write_vip_lineups`, `get_players`, `find_sheet_id` | Deep service — the concrete **`SheetPort` adapter**. |
| `sheets/dfs_sheet_repository.py` | `DfsSheetRepository` | Thin wrapper over `dfs_common` SheetClient (data-access seam). |
| `sheets/sheets_service.py` | `build_dfs_sheet_service`, `make_sheet_client`, `fetch_sheet_gids` | Factory / composition root so entry points need one import. |
| `domain/dfs_sheet_domain.py` | *(see Domain)* | Pure formatting used by the service. |

---

## 5. Analytics

| Module | Interface | Notes |
|---|---|---|
| `analytics/optimizer.py` | `Optimizer.get_optimal_lineup() -> list[Player] \| None` | LP solver (PuLP). **Shallow interface risk:** callers only need `get_optimal_lineup`, but `create_decision_variables`, `define_*_constraint`, `solve_problem`, `extract_optimal_lineup` are all public — internal LP steps leaking through the interface. Candidate to make private. |
| `analytics/trainfinder.py` | `TrainFinder`: `get_total_users`, `get_total_users_above_salary`, `get_users_above_salary_spent` | Clusters users by salary spent ("trains"). |

---

## 6. Lobby package (`lobby/`)

A clean pipeline, each stage a small module:

| Module | Interface | Stage |
|---|---|---|
| `lobby/fetch.py` | `get_dk_lobby`, `get_lobby_response`, `requests_fetch_json` | Fetch raw lobby JSON. |
| `lobby/parsing.py` | `get_contests_from_response`, `build_draft_group_start_map`, `log_draft_group_event` | Response → `Contest` objects. |
| `lobby/draft_group_filter.py` | `filter_draft_groups(groups, sport) -> list[int]` | Sport-specific qualification (canonical in CONTEXT.md). |
| `lobby/contest_filter.py` | `is_double_up_contest`, `filter_double_ups`, `largest_by_entries` | Double-up selection. |
| `lobby/double_ups.py` | `get_double_ups`, `get_stats` | Higher-level double-up queries. |
| `lobby/formatting.py` | `format_discord_messages(contests)` | Presentation. |
| `lobby/common.py` | `valid_date`, `get_salary_date`, `is_time_between` | Shared date helpers. |

---

## 7. Bot (`bot/`)

| Module | Interface | Role |
|---|---|---|
| `bot/discord_bot.py` | `main()` + discord.py commands (`contests`, `live`, `upcoming`, `health`, …) | Long-running Discord bot (entry point). |
| `bot/discord_rest.py` | `DiscordRest` | REST webhook sender — a `BonusSenderPort`-shaped adapter. |
| `bot/botinterface.py` | `BotInterface` | Abstraction over bot messaging. |

---

## 8. CLI & command adapters

**`cli/` — thin adapters** that parse arguments and wire the deep modules; each
exposes `main()`. Root-level scripts (`dkcontests.py`, `db_main.py`,
`find_new_double_ups.py`, `update_contests.py`, `draftables.py`,
`export_fixture.py`, `generate_sheet_gids.py`) are one-import
`sys.path` shims delegating to their `cli/` counterpart.

- `cli/db_main.py` — snapshot payload build/write (`build_snapshot_payload`, `write_snapshot_payload`).
- `cli/update_contests.py` — **large**: contest-completion polling, VIP-presence tracking, soft-finish + bonus announcements, and its own SQLite helpers. A functional module carrying a lot of DB + notification logic (see notes).
- `cli/find_new_double_ups.py` — `process_sport`, upsert, Discord notify.
- `cli/dkcontests.py` — contest discovery + cron-line generation.
- `cli/export_fixture.py` — argparse front for `commands/export_fixture.py`.
- `cli/generate_sheet_gids.py`, `cli/draftables.py`.

**`commands/export_fixture.py`** — the actual export logic behind the CLI:
`run_export_fixture`, `run_export_bundle`, `run_publish_snapshot`.

---

## 9. Cross-cutting infrastructure

| Module | Interface | Role |
|---|---|---|
| `config.py` | `load_settings`, `apply_environment_defaults`, `load_and_apply_settings` | Settings from `dfs_common`. |
| `logging.py` | `configure_logging(level_override)` | Central logging for every entry point. |
| `paths.py` | `find_repo_root`, `repo_root`, `repo_file` | Repo-root-relative path resolution. |
| `persistence/contestdatabase.py` | `ContestDatabase`: `create_table`, `compare_contests`, `insert_contests`, `sync_draft_group_start_dates`, `get_live_contest(s)`, `get_next_upcoming_contest(_any)`, `get_contest_*` | SQLite persistence for contests — deep data-access module, injected into `SportProcessor`. |
| `notifications/bonus_announcements.py` | `announce_vip_bonuses`, `create_bonus_announcements_table`, `BonusCandidate` | Bonus dedupe (CAS on a counter) + webhook delivery. |
| `discord_roles.py` | *(constants/roles)* | Discord role mapping. |

---

## Notes for architecture work (per the *improve-codebase-architecture* skill)

Deletion-test candidates — modules whose removal would *concentrate* complexity
back into callers, i.e. worth keeping/deepening — versus surfaces worth
tightening:

1. **`analytics/optimizer.py` — tighten a shallow interface.** Only
   `get_optimal_lineup()` is needed by callers; the LP-construction steps are
   public. Making them private shrinks the interface without losing behaviour
   (a textbook "hide more complexity inside").
2. **`services/snapshot_v3/` — preserve the contract seams.** Collection,
   derivation, building, normalization, validation, and serialization are kept
   as separate modules behind `build_snapshot_v3_envelope`; extend those seams
   rather than introducing another snapshot generation surface.
3. **`cli/update_contests.py` — a CLI carrying domain logic.** Contest-completion
   detection, VIP-presence, soft-finish announcements, and SQLite helpers live in
   an "adapter" tier. Its DB/notification logic could move into a deep module
   (mirroring how `SportProcessor` extracted the sheet pipeline), leaving the CLI thin.
4. **Ports are the healthy pattern to preserve.** `DkPort`, `SheetPort`,
   `BonusSenderPort`, and `DkHttpPort` are the repo's best seams — keep new
   external-edge behaviour behind protocols rather than concrete imports.
