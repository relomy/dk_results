# NFLShowdown admits two start-time windows, not one 6:00 PM floor

ADR-0013 kept only primetime and marquee Showdowns by requiring a start at or after 6:00 PM ET. That also excluded the Featured Showdown for a morning game: international games kick off at 9:30 AM ET, and a live lobby pull on 2026-10-18 showed draft group 154948 (HOU vs JAX, London) starting at `Sun 9:30AM`. `NFLShowdownSport` now accepts a draft group whose start falls in `[06:00, 13:00)` ET or at or after `18:00` ET, so the morning game (and a Thanksgiving 12:30 PM game) surfaces while the 1:00 PM and afternoon Featured picks stay out.

`Sport.contest_restraint_time` (one floor) is replaced by `Sport.start_windows`, a `tuple[StartWindow, ...] | None` where `None` means unconstrained. `StartWindow` is a `NamedTuple` `(start, end=None)`; windows are half-open, and `end=None` runs to the end of the day. `NFLShowdownSport` is its only user. This is the same single-field collapse as `suffixes` in ADR-0012. The morning game's suffix is `(HOU vs JAX)`, not `(TEAM @ TEAM)`. The existing catch-all suffix pattern already accepts it, so suffix matching is unchanged.

## Considered Options

- **Weekday or date rule**: rejected. International games have moved off Sunday (Friday, Thursday, holiday windows), so a weekday rule would drop them without a trace, and a start time already carries the distinction ADR-0013 needs.
- **Only keep one game live at a time**: rejected for now. A Showdown draft group is already a single game, `GameCount` is the only game-count field on a draft group, and "going on" would need an assumed game length. `_deduplicate_showdown` still drops every group that shares a start minute, and `get_live_contest` still returns one contest per sport.
- **A separate `Sport` for the morning game** (as `NFLAfternoonSport` does): rejected. It would add entries to the client sport-ID map, Discord config, sheet gids and the snapshot sport list, for a game that never overlaps the night game in time.

## Consequences

- The upper bound is exclusive at 13:00 ET and depends on the 1:00 PM window starting at exactly that time (as in the 2026-10-18 pull). A test pins 12:30 admitted and 13:00 rejected.
- Thanksgiving's 4:30 PM game stays excluded: it cannot be told from Sunday's 4:05/4:25 Featured picks by start time.
- The one-Featured-Showdown-per-window assumption rests on two observed weeks (ADR-0013's 2026-09-17 pull and 2026-10-18). The morning game's `Featured` tag was not observed, because the draft group had left the upcoming endpoint by the time it was checked; its shape is assumed to match the other Featured picks.
- A stale morning contest (`completed=0`) that is still unfinished when the night game starts would compete with it in `get_live_contest`, which orders by entry fee, then entries, then latest start. This risk is real and not covered by a passing test: the regression test written for it failed (a stale morning `completed=0` contest with a higher fee or more entries beats the started night contest), and no ordering change has been made. The failing test and the options are tracked on issue #225.
