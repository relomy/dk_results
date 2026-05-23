# dk_results — Architecture Context

## Vocabulary

- **Module** — any unit with an interface and implementation (function, class, package).
- **Interface** — everything a caller must know: types, invariants, error modes, ordering, config.
- **Depth** — leverage at the interface: large behaviour behind a small interface.
- **Seam** — where an interface lives; a place behaviour can be altered without editing in place.
- **Adapter** — a concrete thing satisfying an interface at a seam.
- **Leverage** — what callers get from depth (simpler call sites).
- **Locality** — what maintainers get from depth (changes concentrated in one place).
- **Draft Group Filter** — the module (`lobby/draft_group_filter.py`) that owns all sport-specific draft-group qualification logic: tag filtering, game-type constraint, suffix matching, time constraint, and NFLShowdown deduplication. Public interface: `filter_draft_groups(groups, sport) -> list[int]`.
- **ContestStandings** — the data structure produced by parsing a DraftKings contest's salary and standings CSVs. Owns players, users, VIP list, cash line, and non-cashing stats. Contest metadata (`contest_id`, `name`) stays with callers. Module: `classes/contest_standings.py`.
- **SportProcessor** — the module that owns the full "process one sport, write to sheet" workflow. Public interface: `SportProcessor.run(sport_name, sport_cls) -> int`. Three injected ports: `DkPort` (DraftKings HTTP), `SheetPort` (Google Sheets, via `sheet_factory: Callable[[str], SheetPort]`), `BonusSenderPort` (Discord). `ContestDatabase` is injected directly (local-substitutable). Raises `NoLiveContestError`, `StandingsUnavailableError`, or `StandsParseError` when a sport must be skipped. Module: `sport_processor.py`.

