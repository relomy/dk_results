# dk_results — Module Inventory

Module boundaries, interfaces and deepening candidates, in the vocabulary of the
**codebase-design** skill (module, interface, depth, seam, adapter, leverage,
locality). This file is canonical for module interfaces and policy detail;
`GLOSSARY.md` holds the domain terms.

## Architecture at a glance

```
Root shims (dkcontests.py, db_main.py, …)      thin sys.path adapters → cli.*
  └─ cli/            argument parsing + wiring  (adapters over deep modules)
  └─ sport_processor.py  ORCHESTRATOR      (SportProcessor.run)
            ├─ DkPort  ──── draftkings/client.py + session.py + cookies.py
            ├─ SheetPort ── sheets/dfs_sheet_service → repository → dfs_common
            └─ BonusSenderPort ── bot/discord_rest, dfs_common WebhookSender
```

The dependency arrows point downward toward pure, dependency-light modules. The
three `Protocol` ports in `sport_processor.py` and `DkHttpPort` in
`vip_lineups.py` are the load-bearing **seams** that keep the orchestrator
testable and the HTTP/Sheets/Discord edges substitutable.

---

## 1. Orchestration

### SportProcessor — `sport_processor.py` *(deep)*
The workflow spine. `SportProcessor.run(sport_name, sport_cls) -> int` hides the
entire "find live contest → download rows → parse standings → compute analytics
→ write sheet → announce bonuses" pipeline behind one call.
- **Seams / adapters:** `DkPort` (DraftKings HTTP), `SheetPort` (Google Sheets,
  built via injected `sheet_factory: Callable[[str], SheetPort]`),
  `BonusSenderPort` (Discord). `ContestDatabase` injected directly
  (local-substitutable): read to find the live contest (`get_live_contest`), and
  written each run with the parsed standings' cash line and `VipCashStatus` rows —
  its only write path into that table (ADR-0011).
- **Error modes as control flow:** `NoLiveContestError`,
  `StandingsUnavailableError`, `StandsParseError` signal "skip this sport";
  `SportProcessorConfig` (frozen) carries filesystem/limit config.
- **Depth:** high — the biggest leverage-per-interface unit in the repo.

### CompletionProcessor — `completion_processor/`
`CompletionProcessor.run(conn) -> None` advances each tracked contest and
announces its milestones. Reads its work list from `ContestDatabase`, not from
DraftKings.
- **Injected collaborators:** `ContestDatabase` (work list + state writes),
  `ContestResultsPort` (the only external DraftKings edge), a presence oracle
  (`VipPresence`), and `BonusSenderPort` (Discord); `NotificationStore` is built
  from the run's `conn` for idempotency.
- **Suppression policy** (ADR-0008): warning/live require a confirmed VIP
  (`present` or `unknown_capped`); completed/soft-finish suppress only on `absent`.
- **Notifications flag:** sends are gated by an explicit `notifications_enabled`
  (resolved at the CLI edge from `DISCORD_NOTIFICATIONS_ENABLED`), independent of
  whether a sender is wired: a disabled run still constructs the processor and
  syncs contest state but short-circuits every send.
- **Package:** `processor.py` builds the collaborators from its own
  dependencies and runs warnings → sync → soft-finish; `ports.py` holds
  `PresenceOracle`, the config and the `Now` clock (`now(tz)`, default
  `datetime.datetime.now`); `announcer.py` (`MilestoneAnnouncer`) owns the
  suppression policy, send and record; `messages.py` is pure message text;
  `warnings.py`, `sync.py` (state write-back plus the live/completed
  transition) and `soft_finish.py` each own one milestone.

### Snapshot v3 — `services/snapshot_v3/`
Collects current DraftKings data, derives analytics, and builds the deterministic
schema-3 JSON envelope consumed by downstream systems. Its public orchestration
surface is `pipeline.build_snapshot_v3_envelope`.
- **Collection split:** `collector.py` keeps the IO (DraftKings,
  `ContestDatabase`, salary and standings files) and the orchestration, and
  delegates to pure sibling modules: `contest_selection.py` (selection reason,
  candidate summary, the `ContestRow` built from a DraftKings contest detail when
  the DB misses, contest-state normalization, the **Completed at** guard; the
  reads that resolve the contest stay in `collector._select_contest`),
  `sections.py` (per-section builders from a parsed `ContestStandings`),
  `source_bundle.py` (**ownership remaining**, **field remaining**, standings
  truncation, raw source-bundle assembly) and `vip_normalize.py` (VIP lineup
  rows and `player_key`). Tests patch the IO names on `collector` (`SALARY_DIR`,
  `load_vips`, `fetch_vip_lineups`, `parse_contest_standings`, `Draftkings`,
  `state`, `_collect_source_snapshot`); only `collector` uses them, so keep them
  there.
- **Collector seam:** reads DraftKings and `ContestDatabase` behind injectable
  `dk`/`contest_db` (both default to the real objects, so production callers pass
  neither) and returns a frozen `CollectedSnapshot` bundle for derive and build.
  It closes only a `ContestDatabase` it opened itself. It reads the draft group's
  draftables once per sport to give each player's `matchup` (matched by draftable
  ID, `domain/draftables.py`); a failed read logs one warning and leaves `matchup` out.
- **Validation split:** `validate.py` is the interface: `validate_v3_envelope`
  (blocking) and `collect_presence_warnings` (non-blocking), with `PresenceRule`
  and `PresenceWarningRow` re-exported from `presence_rules.py`. It dispatches per
  sport to `validate_shape.py` (payload and contest shape, id coherence),
  `validate_metrics.py` (the `metrics` section and the known player-key scan),
  `validate_values.py` (shared predicates) and `presence_rules.py` (the
  **Presence rule** checks). Tests patch `pipeline.validate_v3_envelope`; none
  patch these modules.
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
| `domain/sport.py` | `Sport` base + ~22 sport subclasses; registry fns `iter_sports`, `get_sport_choices`, `get_sport`, `require_sport`, `get_lineup_range` | Deep: a large sport taxonomy behind small lookup fns. **Seam:** the registry is discovered from subclasses (`_build_sport_registry`) as a read-only `Mapping`. |
| `domain/contest_standings.py` | `parse_contest_standings(salary_rows, standings_rows, …) -> ContestStandings`; `players_to_values` | Deep pure parser. Contest metadata stays with callers. Cash line `(min_rank, min_cash_pts)` from `_update_cash_stats` (ADR-0011). |
| `domain/lineup.py` | `parse_lineup_string`, `Lineup`, `LockedSlot`, `normalize_name`, `LineupParseError` | Parsing + value object; validates roster slots. |
| `domain/player.py` | `Player` | Athlete value object, per-sport aware. |
| `domain/draftables.py` | `Draftables.from_payload`, `matchups_by_draftable_id` | Draftables adapter: draftable ID → `Matchup` from the draftables payload; pure, no I/O. |
| `domain/user.py` | `User` | DK user value object. |
| `domain/contest.py` | `Contest.from_lobby(dk_dict, sport)`, `is_double_up` / `is_guaranteed` / `is_starred`, `start_dt`; `get_dt_from_timestamp` | Frozen lobby-row DTO (see GLOSSARY **Contest**); maps DraftKings' terse keys (`sd`, `n`, `dg`, …) to readable fields. |
| `domain/bonus_rules.py` | `parse_bonus_counts(sport, stats_description)` | Pure per-sport parsing rules (golf/nba/mlb/soc). |
| `domain/dfs_sheet_domain.py` | `end_col_for_sport`, `data/header/lineup_range_for_sport`, `build_values_for_vip_lineup` | Pure sheet-range + value formatting; no I/O. |

---

## 3. DraftKings access tier

| Module | Interface | Role |
|---|---|---|
| `draftkings/client.py` | `DraftKings`: `get_leaderboard`, `get_contest_detail`, `get_lobby_contests`, `get_draftables`, `get_entry`, `get_contest_entrants_page`, `download_contest_rows`, `download_salary_csv`, `clone_auth_to` | Deep HTTP client — the concrete **`DkPort` adapter**. |
| `draftkings/leaderboard.py` | `leaderboard_cash_cents(row) -> int \| None` | The one payout decoder, used by the snapshot collector and `CompletionProcessor`: the row's `winningValue`, then its `winnings[]` cash items (a non-cash `payoutType` never counts), then a top-level `payout`/`cash`. |
| `draftkings/session.py` | `AuthSession`: `get_session`, `setup_session`, `cj_from_pickle` | Authenticated `requests.Session` construction. |
| `draftkings/cookies.py` | `get_dk_cookies`, `get_browser_cookies`, `load/save_cookies_to_pickle` | Cookie acquisition/persistence seam under AuthSession. |

---

## 4. Google Sheets tier

| Module | Interface | Role |
|---|---|---|
| `sheets/dfs_sheet_service.py` | `DfsSheetService`: `clear_standings/lineups`, `write_players/column(s)`, `add_contest_details/last_updated/min_cash/non_cashing_info/train_info/optimal_lineup`, `write_vip_lineups`, `get_players`, `find_sheet_id` | Deep service — the concrete **`SheetPort` adapter**. |
| `sheets/dfs_sheet_repository.py` | `DfsSheetRepository` | Thin wrapper over `dfs_common` SheetClient (data-access seam). |
| `sheets/sheets_service.py` | `build_dfs_sheet_service`, `make_sheet_client`, `fetch_sheet_gids` | Factory / composition root so entry points need one import. |

**Format plan.** A values-builder returns `CellFormat(row, col, number_format)`
entries (`dfs_common.sheets.NumberFormat`) with its value grid, and
`SheetClient.write_values_with_format` writes both in one call, every write. It
covers the VIP lineup panel (`build_values_for_vip_lineup`) and the standings
grid (`players_to_values`): Salary, Own, Pts and Value. PGA/GOLF standings rows
and the VIP lineup footer have no Value cell. A `NumberFormat` only renders
numeric cells, so `VipPlayer.pts`/`.value` and `VipLineup.pts` carry raw numbers,
not formatted strings.

---

## 5. Analytics

| Module | Interface | Notes |
|---|---|---|
| `analytics/optimizer.py` | `Optimizer(sport_obj, players: dict[str, Player], logger=None, solver=None)` (solver defaults to `PulpCbcSolver`); `get_optimal_lineup() -> list[SelectedPlayer] \| None` | Orchestrator over the `LineupSolver` port. `SelectedPlayer(player, slot)` is frozen and never mutates the shared `Player`; the salary cap comes from `Sport.salary_cap`. `PulpCbcSolver` selects native CBC on macOS arm64 and bundled CBC elsewhere (ADR-0004). |
| `analytics/game_status.py` | `classify_game_status(text) -> GameStatus(remaining, in_play)`, `sport_has_game_status(statuses)`, `UNKNOWN` | Single place that decides which DraftKings game-info texts mean a player is still to score or live; shared by every snapshot "remaining" metric. |
| `analytics/trainfinder.py` | `TrainFinder`: `get_total_users`, `get_total_users_above_salary`, `get_users_above_salary_spent` | Clusters users by salary spent ("trains"). |

---

## 6. Lobby package (`lobby/`)

A clean pipeline, each stage a small module:

| Module | Interface | Stage |
|---|---|---|
| `lobby/fetch.py` | `get_dk_lobby`, `get_lobby_response`, `requests_fetch_json` | Fetch the anonymous Lobby feed (ADR-0009): `getcontests?sport=` (dict of `Contests` + `DraftGroups`, upcoming), `getlivecontests?sport=` (list of in-progress `Contests`). |
| `lobby/parsing.py` | `get_contests_from_response`, `build_draft_group_start_map`, `log_draft_group_event` | Response → `Contest` objects. |
| `lobby/draft_group_filter.py` | `filter_draft_groups(groups, sport) -> list[int]` | Sport-specific qualification: suffixes (ADR-0012), start windows (ADR-0013, ADR-0017). |
| `lobby/contest_filter.py` | `is_double_up_contest`, `filter_double_ups`, `largest_by_entries` | Double-up selection. |
| `lobby/formatting.py` | `format_discord_messages(contests)` | Presentation. |
| `lobby/common.py` | `valid_date`, `get_salary_date`, `is_time_between` | Shared date helpers. |

---

## 7. Bot (`bot/`)

| Module | Interface | Role |
|---|---|---|
| `bot/discord_bot.py` | `main()` + discord.py commands (`contests`, `live`, `upcoming`, `health`, …) | Long-running Discord bot (entry point). |
| `bot/discord_rest.py` | `DiscordRest` | REST webhook sender — a `BonusSenderPort`-shaped adapter. |

---

## 8. CLI & command adapters

**`cli/` — thin adapters** that parse arguments and wire the deep modules; each
exposes `main()`. The root-level scripts of the same names (`dkcontests.py`,
`db_main.py`, …) are one-import `sys.path` shims delegating to their `cli/`
counterpart.

- `cli/db_main.py` — snapshot payload build/write (`build_snapshot_payload`, `write_snapshot_payload`).
- `cli/update_contests.py` — **large**: contest-completion polling, VIP-presence tracking, soft-finish + bonus announcements, and its own SQLite helpers. A functional module carrying a lot of DB + notification logic (see notes).
- `cli/find_new_double_ups.py` — `process_sport`, upsert, Discord notify.
- `cli/dkcontests.py` — contest discovery + cron-line generation.
- `cli/export_fixture.py` — argparse front for `commands/export_fixture.py`.

**`commands/export_fixture.py`** — the actual export logic behind the CLI:
`run_export_fixture`, `run_export_bundle`, `run_publish_snapshot`.

---

## 9. Cross-cutting infrastructure

| Module | Interface | Role |
|---|---|---|
| `config.py` | `RuntimeSettings`, `load_runtime_settings`, `load_settings`, `apply_environment_defaults`, `load_and_apply_settings` | Env > `config.json` > default settings via `dfs_common.config.resolve_settings`; `load_runtime_settings` also parses the sheet-gid and warning-schedule YAML. |
| `logging.py` | `configure_logging(level_override)` | Central logging for every entry point. |
| `paths.py` | `find_repo_root`, `repo_root`, `repo_file` | Repo-root-relative path resolution. |
| `persistence/contestdatabase.py` | `ContestDatabase`: `create_table`, `compare_contests`, `insert_contests`, `sync_draft_group_start_dates`, `get_live_contest(s)`, `get_next_upcoming_contest(_any)`, `get_contest_*`, `replace_vip_cash_status` / `get_vip_cash_status` | SQLite persistence for contests — deep data-access module, injected into `SportProcessor`. `get_contest_by_id` returns a `ContestRow` (ADR-0006); other queries return tuples. |
| `notifications/bonus_announcements.py` | `announce_vip_bonuses`, `create_bonus_announcements_table`, `BonusCandidate` | Bonus dedupe (CAS on a counter) + webhook delivery. |
| `feed/object_store.py`, `feed/r2.py` | `ObjectStore`: `get_json(key) -> dict \| None`, `put_json(key, body, content_type="application/json")`; `R2ObjectStore` | Snapshot-feed object-store port and its boto3 adapter (ADR-0007). The feed builds through `db_main.build_live_snapshot`, so per-sport `status`/`error` carries partial failure. |
| `discord_announcements.py` | `build_milestone_announcement`, `build_soft_finish_announcement`, `build_bonus_achievement_announcement`, `build_double_up_found_announcement`, `sport_emoji`, `sheet_link`, `DISCORD_ROLE_MAP` | Shared Discord announcement chrome for all 6 push-notification kinds; also owns the double-up-found sport gate. |

---

## Notes for architecture work (per the *improve-codebase-architecture* skill)

Deletion-test candidates: modules whose removal would concentrate complexity
back into callers (worth keeping or deepening), and surfaces worth tightening.

1. **`analytics/optimizer.py` — preserve the tightened interface.** `Optimizer`
   exposes only `get_optimal_lineup()`; the LP construction is private to
   `PulpCbcSolver` behind the `LineupSolver` port (ADR-0004).
2. **`services/snapshot_v3/` — preserve the contract seams.** Extend the
   collection, derivation, building, normalization, validation and serialization
   modules behind `build_snapshot_v3_envelope` rather than adding another
   snapshot generation surface.
3. **`cli/update_contests.py` — a CLI carrying domain logic.** Contest-completion
   detection, VIP-presence, soft-finish announcements, and SQLite helpers live in
   an "adapter" tier. Its DB/notification logic could move into a deep module
   (mirroring how `SportProcessor` extracted the sheet pipeline), leaving the CLI thin.
