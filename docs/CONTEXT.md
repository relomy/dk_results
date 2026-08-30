# dk_results — Architecture Context

## Vocabulary

- **Module** — any unit with an interface and implementation (function, class, package).
- **Interface** — everything a caller must know: types, invariants, error modes, ordering, config.
- **Depth** — leverage at the interface: large behaviour behind a small interface.
- **Seam** — where an interface lives; a place behaviour can be altered without editing in place.
- **Adapter** — a concrete thing satisfying an interface at a seam.
- **Leverage** — what callers get from depth (simpler call sites).
- **Locality** — what maintainers get from depth (changes concentrated in one place).
- **Player** — an athlete available for selection in a contest slate, with a sport position, salary, and contest performance data.
- **User** — a named contest participant represented in standings, associated with one submitted lineup.
- **Lineup** — a user's roster of player assignments for a sport variant. Each slot is either associated with a known `Player` or is explicitly locked before that player's identity is available; an ordinary unresolved player reference makes the lineup invalid.
- **Draft Group Filter** — the module (`lobby/draft_group_filter.py`) that owns all sport-specific draft-group qualification logic: tag filtering, game-type constraint, suffix matching, time constraint, and NFLShowdown deduplication. Public interface: `filter_draft_groups(groups, sport) -> list[int]`.
- **Contest** — the parsed DraftKings *lobby row*: a frozen, read-only DTO validated once at the DraftKings-payload boundary via `Contest.from_lobby(dk_dict, sport)` and then flowed inward unchanged through its consumers (`contest_filter`, `double_ups`, `formatting`). Maps DraftKings' terse keys (`sd`, `n`, `dg`, …) to readable fields and exposes `is_double_up` / `is_guaranteed` / `is_starred` flags and a `start_dt` accessor. Module: `domain/contest.py`.
  _Avoid_: ContestStandings (parsed salary/standings CSVs, not the lobby row); ContestDatabase (stored SQLite contest rows, not the lobby DTO).
- **ContestStandings** — the data structure produced by parsing a DraftKings contest's salary and standings CSVs. Owns players, users, VIP list, cash line, and non-cashing stats. Contest metadata (`contest_id`, `name`) stays with callers. Module: `domain/contest_standings.py`.
- **Remaining salary** — the unspent portion of a user's lineup budget. It is part of the `User` domain state and is distinct from the snapshot's slot-weighted average salary for unfinished players.
- **Format plan** — the list of `CellFormat(row, col, number_format)` entries a values-builder returns alongside the value grid it already knows the layout of, naming which cells need which `dfs_common.sheets.NumberFormat` (e.g. `CURRENCY`). Self-healing: the write path reasserts it on every write via `SheetClient.write_values_with_format` (`dfs_common.sheets`), rather than depending on formatting set once, by hand, directly in the sheet. First established for the VIP lineup panel's Salary cells (`build_values_for_vip_lineup`, `domain/dfs_sheet_domain.py`); see relomy/dk_results#86 and relomy/dfs-common#9.
  _Avoid_: applying a `NumberFormat` via a second, separate write call — the point of the pattern is a single combined values+format write.
- **Cashing** — an entry has a positive realized payout. The availability of payout data is a separate fact and does not by itself mean the entry is cashing.
- **Snapshot artifact** — the canonical schema-3 JSON output produced for downstream consumers. Rollback restores a known-good artifact or producer version; it does not require runtime compatibility with retired schemas.
- **Optimizer** — the orchestrator that solves for a single sport's optimal lineup. Constructed with a `Sport`, a `dict[str, Player]`, and an injectable `LineupSolver` (default `PulpCbcSolver`); its public interface is `get_optimal_lineup() -> list[SelectedPlayer] | None`, where `SelectedPlayer(player, slot)` is a frozen pairing that never mutates the shared `Player`. It reads the salary cap from `Sport.salary_cap`. Module: `analytics/optimizer.py`.
- **LineupSolver** — the port the Optimizer solves behind, keeping the LP backend swappable: `solve(players, positions, salary_cap) -> list[Assignment] | None`, with `Assignment(player_key, slot)`. No PuLP type crosses the boundary. `PulpCbcSolver` is the executable-free default adapter (PuLP's bundled CBC, no external `glpsol`); GLPK is retired and HiGHS (`highspy`) is the sanctioned next backend. See ADR-0004. Module: `analytics/lineup_solver.py`.
- **Roster slot** — one fillable position in a lineup. `Sport.positions` enumerates every slot with its multiplicity (NFL lists `RB` twice, Golf lists `G` six times) and is the **sole source of truth** for a lineup's required composition and size: the solver fills exactly one player per listed slot. A player may fill a slot only if that slot appears in the player's `roster_pos` — DraftKings' per-player slot eligibility. Flex slots (`FLEX`, `G`, `F`, `UTIL`, `S-FLEX`) are ordinary slots whose eligibility DraftKings already encodes in `roster_pos`, so no separate flex model is needed. See ADR-0005.
  _Avoid_: min/max position ranges (`positions_count` / `position_constraints` — an abandoned alternative model, retired in ADR-0005).
- **Optimizer eligibility** — whether a sport's lineups are optimized, carried by `Sport.allow_optimizer`. Defaults to `False` (opt-in): a sport is optimized only once its `positions` layout is confirmed against real DraftKings data, so an unverified sport never silently ships a wrong lineup. Enabled: NFL, NBA, MLB, SOC, CFB, GOLF, WeekendGolf. Showdown variants stay off pending a captain-multiplier model, and XFL/USFL and other unconfirmed sports are held off. See ADR-0005.

- **SportProcessor** — the module that owns the full "process one sport, write to sheet" workflow. Public interface: `SportProcessor.run(sport_name, sport_cls) -> int`. Three injected ports: `DkPort` (DraftKings HTTP), `SheetPort` (Google Sheets, via `sheet_factory: Callable[[str], SheetPort]`), `BonusSenderPort` (Discord). `ContestDatabase` is injected directly (local-substitutable). Raises `NoLiveContestError`, `StandingsUnavailableError`, or `StandsParseError` when a sport must be skipped. Module: `sport_processor.py`.

- **ContestDatabase** — the single boundary for reading and writing contest rows in SQLite (live, upcoming, incomplete, and completion state). Module: `persistence/contestdatabase.py`.
  _Avoid_: NotificationStore (owns notification/presence rows, not contests); ContestResultsPort (live DraftKings readouts, not stored rows).
- **ContestRow** — the named, frozen shape returned by `ContestDatabase.get_contest_by_id` and built from a DraftKings contest detail by the snapshot collector; replaces positional tuple indexing for the by-id contest read. The four trailing fields (`contest_state`, `contest_completed`, `prize_pool`, `max_entries_per_user`) are DK-detail-only and default to `None` on a DB read. See ADR-0006. The other `ContestDatabase` queries still return positional tuples.
- **Snapshot collector** — the collect step of the snapshot v3 pipeline (`services/snapshot_v3/collector.py`). Resolves one contest, reads its DraftKings and `ContestDatabase` data behind an injectable `dk`/`contest_db` seam (both default to the real objects, so production callers pass neither), and returns a frozen `CollectedSnapshot` bundle that flows into derive and build. Only closes a `ContestDatabase` it opened itself. Pure section shaping lives in `sections.py`.

## Contest completion & notifications

- **CompletionProcessor** — the module that advances each tracked contest and announces its milestones: warning, live, completed, soft-finish. Public interface: `CompletionProcessor.run(conn) -> None`. Injected collaborators: `ContestDatabase` (work list + state writes), `ContestResultsPort` (the only external DraftKings edge), a presence oracle (`VipPresence`), and `BonusSenderPort` (Discord); `NotificationStore` is built from the run's `conn` for idempotency. Reads its work list from `ContestDatabase`, not from DraftKings. Owns the suppression policy, which differs by milestone: warning/live require a confirmed VIP (`present` or `unknown_capped`); completed/soft-finish keep the original looser policy (only `absent` suppresses). See ADR-0008. Announcements are gated by an explicit `notifications_enabled` flag (resolved at the CLI edge from `DISCORD_NOTIFICATIONS_ENABLED`), independent of whether a sender is wired: a disabled run still constructs the processor and syncs contest state but short-circuits every send. Module: `completion_processor.py`.
- **Notification event** — the identity of a single announcement about a contest, used to keep announcing idempotent. One per milestone: starting-soon warning, live, completed, soft-finish.
- **NotificationStore** — persistence that keeps a milestone from being announced twice, and caches VIP presence. Module: `persistence/notification_store.py`.
  _Avoid_: ContestDatabase (owns contest rows, not notifications).
- **Warning schedule** — the per-sport list of "minutes before start" at which a starting-soon warning fires, with a default.
  _Avoid_: cron interval (schedules the run itself, not the warning).
- **Soft-finish** — the state where a live contest's scoring is effectively final though DraftKings has not marked it COMPLETED; triggers a VIP-cash summary.
  _Avoid_: completed / CANCELLED (DraftKings' own terminal statuses).
- **VipPresence** — the oracle answering whether a tracked VIP is entered in a contest, returning a presence verdict. Short-circuits at the first tracked VIP found; never enumerates the full entrant list, so it proves presence/absence but not the complete roster of who's in. Module: `notifications/vip_presence.py`.
- **Presence verdict** — a VipPresence result: `present`, `absent`, `unknown`, or `unknown_capped`. `unknown_capped` is a structural variant of `unknown` — the entrant-page cap was hit before a conclusive read, because the field is too large to fully scan, not because of a transient failure. Suppression policy differs by milestone (see below): warning and live require a *confirmed* verdict (`present` or `unknown_capped`); completed and soft-finish keep the original looser policy (only `absent` suppresses; any `unknown` allows). See ADR-0008.
- **ContestResultsPort** — the seam through which the completion workflow reads one contest's live DraftKings readouts — state, entrants, leaderboard — by `dk_id`.
  _Avoid_: lobby feed (source of new contests); stored contest state (`ContestDatabase.get_contest_state`).

## Snapshot feed to the dashboard

The **snapshot feed** is the committed, scheduled replacement for the hand-run
`export_fixture … && export_fixture publish && wrangler r2 object put …` recipe.
Each cycle runs **build → publish → load**: build one multi-sport snapshot
artifact, derive the latest pointer and day manifest, and load `snapshots/*`,
`manifest/*`, and `latest.json` into the object store the dashboard reads
(R2 bucket `dk-dashboard-data`). Entry point: `snapshot_feed.py:main`, an
externally-scheduled `main()` on the existing Pi scheduler. See ADR-0007.

- **Object store** — the keyed JSON store the feed loads into and the dashboard
  reads from. Port: `ObjectStore` with `get_json(key) -> dict | None` and
  `put_json(key, body, content_type="application/json")`, injected into the
  pipeline. Default adapter is `R2ObjectStore` (boto3 against R2's
  S3-compatible endpoint); tests substitute a fake in-memory store at this seam.
  Modules: `feed/object_store.py`, `feed/r2.py`.
  _Avoid_: `wrangler` (rejected in ADR-0007); the dashboard's HTTP API (a
  separate read edge — the feed writes object keys, not `/api/*`).
- **Snapshot artifact** — the schema-3 multi-sport envelope built via the
  DB-driven `db_main.build_live_snapshot` path, so the database decides which
  contests are live and per-sport `status`/`error` carries partial failure.
- **Latest pointer** — `latest.json`, naming the current snapshot key plus the
  today/yesterday manifest paths. Uploaded **last** each cycle; a failed upload
  leaves the previous pointer intact so the dashboard never resolves a missing
  key. Derived by the reused publish step.
- **Day manifest** — `manifest/<date>.json`, the UTC-day list of that day's
  snapshots. The producer is stateless: the manifest is read from the object
  store, appended, and written back each cycle. Snapshot keys are immutable and
  timestamped; a 30-day bucket lifecycle rule ages `snapshots/` and `manifest/`
  out (bucket-side, not code).
  _Avoid_: local snapshot state on the Pi (there is none — the object store is
  the source of truth).
