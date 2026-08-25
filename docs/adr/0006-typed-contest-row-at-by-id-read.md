# A typed `ContestRow` at the `get_contest_by_id` read

`ContestDatabase.get_contest_by_id` now returns a frozen `ContestRow` dataclass
instead of a bare positional tuple, and the snapshot collector's
`_contest_row_from_detail` builds the same type. This removes the `len()`/magic-index
ladder in `_collect_source_snapshot`, where the contest row's column *count* was a
hand-checked runtime invariant reconciling a 7-column DB read against an 11-field
DK-detail fallback (issue #75, finding 4). Field access is now by name, and a
column reorder in the query surfaces as a type/field error rather than silently
corrupting downstream fields.

## Scope: one projection, deliberately

`ContestDatabase` exposes **six** contest-row queries, each a *different* column
projection in a different order (`get_incomplete_contests` is a 9-column shape,
`get_live_contest` a 5-column one, `get_live_contest_candidates` a 6-column one,
etc.). There is no single universal "contest row" to unify them. We typed only
`get_contest_by_id` — the read the collector's selection ladder actually consumes —
rather than typing all six at once (a large, mechanical change beyond a
maintainability pass) or leaving the ladder in place with a comment (loses the
type-checked shape the finding asked for). The other five projections stay tuples
until a caller's clarity earns the same treatment.

## Consequence

`ContestRow`'s four trailing fields (`contest_state`, `contest_completed`,
`prize_pool`, `max_entries_per_user`) are populated only by the DK-detail
constructor and default to `None` on a by-id DB read — the shape is a superset of
the DB query so both sources produce one type. Scalar fields stay `Any`: the values
are the heterogeneous scalars SQLite and the DK payload return, and the win is the
*named, ordered* shape, not per-field precision.
