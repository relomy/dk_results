# NFLShowdownSport requires a 6:00 PM ET start floor

`NFLShowdownSport` matched any `Featured`, `GameTypeId=96` draft group with an
ordinary suffix. Live DraftKings data (pulled 2026-09-17) showed this is
broader than intended: DraftKings tags one `Featured` Showdown *per game
window*, not just the single-game primetime slate — a normal Sunday produced
three `Featured` Showdown draft groups: the Thursday-night game (20:15 ET),
one from the 1:00 PM window, and one from the 4:25 PM window. Suffix text and
game type are identical in shape across all three (`(TEAM @ TEAM)`,
`GameTypeId=96`), so neither can tell primetime apart from a day-window pick.

`ContestDatabase.get_live_contest` already guarantees only one contest is
ever selected as "live" for a given sport at read time (`LIMIT 1` with
deterministic tie-breaking), so this isn't a concurrency-safety fix — DK's
own day-window Featured Showdowns just aren't contests this operator wants
tracked under `NFLShowdown` at all.

Fix: set `NFLShowdownSport.contest_restraint_time = time(18, 0)`, using the
existing (previously unused, commented-out) `contest_restraint_time` /
`_passes_time` seam. `_passes_time` requires `dt_start.time() >=
contest_restraint_time`, so any draft group starting before 6:00 PM ET is
rejected regardless of tag/suffix/game-type match.

6:00 PM, not 8:00 PM: regular-season primetime games (Thu/Sun/Mon night) kick
off ~20:15–20:20 ET, but the Super Bowl kicks off ~18:30 ET — an existing
test (`test_filter_draft_groups_nfl_showdown_super_bowl_suffix`) already
encodes this and would have broken under an 8:00 PM floor. A normal Sunday's
day windows (1:00 PM, 4:05/4:25 PM) never start as late as 6:00 PM, so a
6:00 PM floor keeps every single-game primetime/marquee slate while
excluding every standard day-window Featured pick.
