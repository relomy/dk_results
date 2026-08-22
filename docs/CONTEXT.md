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
- **ContestStandings** — the data structure produced by parsing a DraftKings contest's salary and standings CSVs. Owns players, users, VIP list, cash line, and non-cashing stats. Contest metadata (`contest_id`, `name`) stays with callers. Module: `domain/contest_standings.py`.
- **SportProcessor** — the module that owns the full "process one sport, write to sheet" workflow. Public interface: `SportProcessor.run(sport_name, sport_cls) -> int`. Three injected ports: `DkPort` (DraftKings HTTP), `SheetPort` (Google Sheets, via `sheet_factory: Callable[[str], SheetPort]`), `BonusSenderPort` (Discord). `ContestDatabase` is injected directly (local-substitutable). Raises `NoLiveContestError`, `StandingsUnavailableError`, or `StandsParseError` when a sport must be skipped. Module: `sport_processor.py`.

- **ContestDatabase** — the single boundary for reading and writing contest rows in SQLite (live, upcoming, incomplete, and completion state). Module: `classes/contestdatabase.py`.
  _Avoid_: NotificationStore (owns notification/presence rows, not contests); ContestResultsPort (live DraftKings readouts, not stored rows).

## Contest completion & notifications

- **CompletionProcessor** — the module that advances each tracked contest and announces its milestones: warning, live, completed, soft-finish. Public interface: `CompletionProcessor.run(conn) -> None`. Injected collaborators: `ContestDatabase` (work list + state writes), `ContestResultsPort` (the only external DraftKings edge), a presence oracle (`VipPresence`), and `BonusSenderPort` (Discord); `NotificationStore` is built from the run's `conn` for idempotency. Reads its work list from `ContestDatabase`, not from DraftKings. Owns the suppression policy: an `absent` presence verdict suppresses an announcement, `unknown` allows it. Announcements are gated by an explicit `notifications_enabled` flag (resolved at the CLI edge from `DISCORD_NOTIFICATIONS_ENABLED`), independent of whether a sender is wired: a disabled run still constructs the processor and syncs contest state but short-circuits every send. Module: `completion_processor.py`.
- **Notification event** — the identity of a single announcement about a contest, used to keep announcing idempotent. One per milestone: starting-soon warning, live, completed, soft-finish.
- **NotificationStore** — persistence that keeps a milestone from being announced twice, and caches VIP presence. Module: `classes/notification_store.py`.
  _Avoid_: ContestDatabase (owns contest rows, not notifications).
- **Warning schedule** — the per-sport list of "minutes before start" at which a starting-soon warning fires, with a default.
  _Avoid_: cron interval (schedules the run itself, not the warning).
- **Soft-finish** — the state where a live contest's scoring is effectively final though DraftKings has not marked it COMPLETED; triggers a VIP-cash summary.
  _Avoid_: completed / CANCELLED (DraftKings' own terminal statuses).
- **VipPresence** — the oracle answering whether a tracked VIP is entered in a contest, returning a presence verdict. Module: `classes/vip_presence.py`.
- **Presence verdict** — a VipPresence result: `present`, `absent`, or `unknown`. `absent` suppresses announcements; `unknown` allows them.
- **ContestResultsPort** — the seam through which the completion workflow reads one contest's live DraftKings readouts — state, entrants, leaderboard — by `dk_id`.
  _Avoid_: lobby feed (source of new contests); stored contest state (`ContestDatabase.get_contest_state`).
