# Collapse Sport suffix config to one field; NFLSport is suffixless-only

`Sport` used to express suffix matching across two independently-defaulting
fields: `suffixes: tuple[str, ...] = ()` and
`allow_suffixless_draft_groups: bool = True`. `_passes_suffix`'s fallback for
an empty `suffixes` tuple was "accept any suffix" — a fail-open default. That
shape let `NFLSport` (suffixes unset, `allow_suffixless_draft_groups`
inherited as `True`) claim every real Classic-gameType draft group DraftKings
publishes, suffixed or not — `(Afternoon Only)`, `(Thu-Mon)`, `(Sun-Mon)`,
`(Early Only)`, `(Afternoon Turbo)` — the same shape of leak that produced the
Showdown/Tiers `LineupParseError` crash loops fixed by restraining
`contest_restraint_game_type_id` in #144, just on the suffix axis instead of
the game-type axis. `NFLAfternoonSport` had the same gap in miniature: its
`(Afternoon Only)` pattern had no game-type restraint, so it would also have
claimed Tiers (`gameTypeId=51`) and Snake (`gameTypeId=189`) draft groups
sharing that suffix text.

`Sport.suffixes` is now the single field: `tuple[str | None, ...] | None`.

- `None` — unconstrained: any suffix, or none, passes (today's prior default).
- `()` — must be suffixless.
- `(p1, p2, ...)` — suffix must match one of these patterns; suffixless
  rejected.
- `(None, p1, p2, ...)` — suffixless OR one of these patterns.

`NFLSport.suffixes = ()`: suffixless-only, so a Showdown/Tiers/Snake/Afternoon
contest can never be selected as the live "NFL" contest by suffix alone.
`NFLAfternoonSport` keeps its `(Afternoon Only)` pattern and gains
`contest_restraint_game_type_id = 1`, scoping it to Classic the same way
`NFLSport` was scoped in #144. `NFLShowdownSport`'s existing
suffixless-or-pattern behavior is preserved exactly as
`(None, r"\(\w{2,3} @ \w{2,3}\)", r"\([A-Za-z0-9 .'-]+\)")`. Every other
`Sport` subclass keeps the new default (`None`), a no-op migration.

`_passes_suffix` no longer has an implicit fail-open branch: an empty
`suffixes` tuple now means "reject every suffixed group," not "accept any
suffix." A future `Sport` subclass can no longer reintroduce this class of
leak by leaving `suffixes` unset to `()`.

Deferred: the Golf cluster (`GolfSport`, `PGAMainSport`, `PGAWeekendSport`,
`PGAShowdownSport`, `WeekendGolfSport`) has the same shape of gap — none set
`allow_suffixless_draft_groups`, so all were suffixless-open — but there was
no live PGA slate to verify real suffix/`gameTypeId` combinations against
when this was written. Left as unconstrained (`None`) pending a follow-up
spec with live data. Also deferred: tracking `(Thu-Mon)`, `(Sun-Mon)`,
`(Early Only)`, or `(Afternoon Turbo)` NFL contests under any sport —
`NFLSport` rejects them outright and nothing else claims them; that is
intentional for now, not an oversight.
