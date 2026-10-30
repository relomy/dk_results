# dk_results — Architecture and module boundaries

This guide records durable architecture: dependency direction, module
interfaces, seams, constraints, and rationale. It is not a catalog of every
symbol or source file. Domain terms live in [`GLOSSARY.md`](../GLOSSARY.md), and
decisions live in [`adr/`](adr/).

## Architecture at a glance

```
Root shims (dkcontests.py, db_main.py, …)      thin sys.path adapters → cli.*
  └─ cli/            argument parsing + wiring  (adapters over deep modules)
  └─ sport_processor.py  ORCHESTRATOR      (SportProcessor.run)
            ├─ DkPort  ──── draftkings/client.py + session.py + cookies.py
            ├─ SheetPort ── sheets/dfs_sheet_service → repository → dfs_common
            └─ BonusSenderPort ── bot/discord_rest, dfs_common WebhookSender
```

Dependencies point toward pure, dependency-light modules. The three `Protocol`
ports in `sport_processor.py` and `DkHttpPort` in `vip_lineups.py` are the
load-bearing seams that keep orchestration testable and HTTP, Sheets, and
Discord edges substitutable.

## 1. Orchestration

### SportProcessor — `sport_processor.py`

The workflow spine. `SportProcessor.run(sport_name, sport_cls) -> int` hides the
"find live contest → download rows → parse standings → compute analytics → write
sheet → announce bonuses" pipeline behind one call.

- **Seams / adapters:** `DkPort` (DraftKings HTTP), `SheetPort` (Google Sheets,
  built via injected `sheet_factory: Callable[[str], SheetPort]`), and
  `BonusSenderPort` (Discord). `ContestDatabase` is injected directly and is
  locally substitutable: it reads the live contest and is written each run with
  the parsed standings' cash line and `VipCashStatus` rows, its only write path
  into that table (ADR-0011).
- **Error modes as control flow:** `NoLiveContestError`,
  `StandingsUnavailableError`, and `StandsParseError` signal "skip this sport";
  frozen `SportProcessorConfig` carries filesystem and limit config.
- **Depth:** high — the biggest leverage-per-interface unit in the repo.

### CompletionProcessor — `completion_processor/`

`CompletionProcessor.run(conn) -> None` advances each tracked contest and
announces milestones. It reads its work list from `ContestDatabase`, not
DraftKings.

- **Injected collaborators:** `ContestDatabase` (work list and state writes),
  `ContestResultsPort` (the external DraftKings edge), the `VipPresence` oracle (standings poll first, ADR-0018),
  and `BonusSenderPort` (Discord); `NotificationStore` is built from the run's
  connection for idempotency.
- **Suppression policy** (ADR-0008): warning/live require a confirmed VIP
  (`present` or `unknown_capped`); completed/soft-finish suppress only on
  `absent`.
- **Notifications flag:** sends are gated by explicit `notifications_enabled`
  (resolved at the CLI edge from `DISCORD_NOTIFICATIONS_ENABLED`), independent
  of whether a sender is wired. A disabled run still constructs the processor
  and syncs contest state, then short-circuits every send.
- **Collaborator ownership:** `processor.py` builds collaborators from its
  dependencies and runs warnings → sync → soft-finish. `ports.py` holds
  `PresenceOracle`, config, and the `Now` clock (`now(tz)`, default
  `datetime.datetime.now`). `MilestoneAnnouncer` owns suppression, sending, and
  recording; message text is pure. `warnings.py`, `sync.py`, and
  `soft_finish.py` each own one milestone.

### Snapshot v3 — `services/snapshot_v3/`

Collects current DraftKings data, derives analytics, and builds the deterministic
schema-3 JSON envelope consumed downstream. Its single public orchestration
surface is `pipeline.build_snapshot_v3_envelope`.

- **Collection boundary:** `collector.py` owns I/O (DraftKings,
  `ContestDatabase`, salary and standings files) and orchestration. Pure sibling
  modules `contest_selection.py`, `sections.py`, `source_bundle.py`, and
  `vip_normalize.py` handle contest selection, section construction,
  source-bundle assembly, and VIP normalization. Contest-selection helpers
  include the selection reason, candidate summary, fallback `ContestRow`, state
  normalization, and **Completed at** guard; contest-resolving reads remain in
  `collector._select_contest`. The source bundle owns **ownership remaining**,
  **field remaining**, standings truncation, and raw bundle assembly.
- **Patch seam:** tests patch the I/O names on `collector` because that module
  alone uses them; keep those names there.
- **Collector seam:** DraftKings and `ContestDatabase` are injectable through
  `dk`/`contest_db` (both default to real objects). The collector returns a
  frozen `CollectedSnapshot` for derive and build, and closes only a database it
  opened. It reads each sport's draftables once to set player `matchup` by
  draftable ID; a failed read logs one warning and omits `matchup`.
- **Validation boundary:** `validate.py` is the interface for blocking
  `validate_v3_envelope` and non-blocking `collect_presence_warnings`. It
  dispatches to `validate_shape.py`, `validate_metrics.py`, `validate_values.py`,
  and `presence_rules.py` for shape, metrics, shared-value, and **Presence rule**
  checks. The public pipeline remains the patch seam for validation.
- **Depth:** high — external collection stays at the boundary and there is one
  schema-3 generation path.

### VIP Lineups — `vip_lineups.py`

`fetch_vip_lineups(...)` gathers VIP entries and parses scorecards into
`VipLineup`/`VipPlayer` values. The `DkHttpPort` protocol makes the DraftKings
fetch injectable; `load_vips()` and `build_vip_entries()` complete the module's
interface.

## 2. Domain (pure, dependency-light)

Domain values and parsers sit below external adapters. `parse_contest_standings`
builds `ContestStandings`, which owns standings-derived data and the cash line;
contest metadata stays with callers (ADR-0011). `parse_lineup_string` builds a
validated `Lineup`; `Draftables.from_payload` maps DraftKings draftable IDs to
`Matchup` values without I/O. `Contest.from_lobby` creates the frozen lobby-row
value at the DraftKings boundary, then callers pass it inward unchanged.

`Sport.positions` is the source of truth for roster composition (ADR-0005), and
the sport registry is discovered from subclasses as a read-only `Mapping`.
`end_col_for_sport` and sheet-domain builders provide the ranges and values used
by the Sheets adapter; `data`, `header`, and `lineup_range_for_sport` define its
layout boundaries.
`domain/bonus_rules.py` parses per-sport bonus counts from stats descriptions
for Golf, NBA, MLB, and soccer.
See [`GLOSSARY.md`](../GLOSSARY.md) for domain ownership and vocabulary.

## 3. DraftKings access tier

`draftkings/client.py` is the concrete `DkPort` adapter and owns HTTP access.
`AuthSession` constructs authenticated `requests.Session` instances;
`draftkings/cookies.py` is the cookie acquisition and persistence seam beneath
it. Payout decoding is centralized in `draftkings/leaderboard.py`: the
`winningValue`, cash items in `winnings[]`, then top-level `payout`/`cash` are
considered, and a non-cash `payoutType` never counts.

## 4. Google Sheets tier

`DfsSheetService` is the concrete `SheetPort` adapter. It uses
`DfsSheetRepository`, a thin data-access wrapper around `dfs_common`'s
`SheetClient`; `sheets_service.py` composes them for entry points. The service
owns sheet reads and writes: clearing standings/lineups, writing player and VIP
lineup grids, updating contest metadata, and reading sheet players and IDs.

**Format plan.** `build_values_for_vip_lineup` and `players_to_values` return
their value grids with `CellFormat(row, col, number_format)` entries, and
`SheetClient.write_values_with_format` writes both together on every write.
This covers the VIP lineup panel and standings grid: Salary, Own, Pts, and
Value. PGA/GOLF standings rows and the VIP lineup footer have no Value cell.
`NumberFormat` only renders numeric cells, so `VipPlayer.pts`/`.value` and
`VipLineup.pts` carry raw numbers, not formatted strings.

## 5. Analytics

`Optimizer` orchestrates behind the `LineupSolver` port and exposes
`get_optimal_lineup()`; LP construction stays private to `PulpCbcSolver`
(ADR-0004). The solver selects native CBC on macOS arm64 and bundled CBC
elsewhere. Returned `SelectedPlayer(player, slot)` values are frozen and do not
mutate their shared `Player`; the salary cap comes from `Sport.salary_cap`.
`analytics/game_status.py` is the single owner of DraftKings game-info
classification shared by snapshot "remaining" metrics.
`analytics/trainfinder.py` defines `TrainFinder`, which clusters users by salary
spent.

## 6. Lobby package (`lobby/`)

The lobby pipeline fetches anonymous DraftKings payloads in `fetch.py`
(ADR-0009): `getcontests?sport=` returns upcoming contests and draft groups,
while `getlivecontests?sport=` returns in-progress contests. `parsing.py`
converts them to `Contest` values. `draft_group_filter.py` owns the `Draft Group
Filter`'s sport-specific qualification rules, including suffix, start-window,
and NFLShowdown behavior (ADR-0012, ADR-0013, ADR-0017), behind
`filter_draft_groups(groups, sport) -> list[int]`. `contest_filter.py` owns the
separate double-up selection concern. `formatting.py` exposes
`format_discord_messages(contests)` for local operator visibility. `common.py`
centralizes date validity, salary-date, and time-window helpers.

## 7. Bot (`bot/`)

`bot/discord_bot.py` is the long-running entry point over the same announcement
and workflow modules as scheduled commands; it registers the contests, live,
upcoming, and health commands. `DiscordRest` is the REST webhook adapter shaped
for `BonusSenderPort`.

## 8. CLI and command adapters

`cli/` modules parse arguments and wire deeper modules; root scripts such as
`dkcontests.py` and `db_main.py` are one-import `sys.path` shims to their CLI
counterparts. `commands/export_fixture.py` owns export behavior behind its CLI.

`cli/update_contests.py` remains a known architecture pressure point: contest
completion, VIP-presence tracking, soft-finish and bonus announcements, and
SQLite helpers sit in the adapter tier. Its DB and notification logic could move
to a deep module, as the sheet pipeline did with `SportProcessor`.

## 9. Cross-cutting infrastructure

- **Runtime configuration:** `config.py` resolves environment values before
  `config.json` and defaults, parses sheet-gid and warning-schedule YAML, and
  owns runtime bootstrap. Executables load repository configuration once and
  pass frozen `RuntimeSettings` inward; imports do not configure the process
  (ADR-0009).
- **Contest persistence:** `ContestDatabase` is the deep SQLite boundary for
  contest rows and is injected into workflows. It owns reads for live, upcoming,
  incomplete, and completion state, plus contest synchronization and VIP cash
  status writes. `get_contest_by_id` returns a `ContestRow` (ADR-0006); other
  queries return tuples. `NotificationStore` separately owns notification and
  VIP-presence state.
- **Snapshot storage:** `ObjectStore` exposes `get_json(key)` and
  `put_json(key, body, content_type)`; `R2ObjectStore` is its boto3 adapter
  (ADR-0007). The feed builds through `db_main.build_live_snapshot`, so
  per-sport `status`/`error` carries partial failure.
- **Bonus announcements:** `notifications/bonus_announcements.py` combines
  bonus deduplication (compare-and-set on a counter) with webhook delivery.
- **Announcements:** `discord_announcements.py` owns shared message chrome for
  push notifications and bot commands (ADR-0010).

## Notes for architecture work

Deletion-test candidates are modules whose removal would concentrate complexity
into callers, and surfaces worth tightening.

1. **`analytics/optimizer.py` — preserve the tightened interface.** `Optimizer`
   exposes only `get_optimal_lineup()`; LP construction is private to
   `PulpCbcSolver` behind `LineupSolver` (ADR-0004).
2. **`services/snapshot_v3/` — preserve the contract seams.** Extend collection,
   derivation, building, normalization, validation, and serialization behind
   `build_snapshot_v3_envelope` rather than adding another snapshot generation
   surface.
3. **`cli/update_contests.py` — a CLI carrying domain logic.** Contest-completion
   detection, VIP-presence, soft-finish announcements, and SQLite helpers could
   move into a deep module, leaving the CLI thin.
