# `completed_at` is stamped in the contest database, not derived from the object store

The dashboard needs to land on the most recently completed primary contest, so a `Contest` in the snapshot feed carries an optional `completed_at`: the UTC moment the producer first observed DraftKings reporting the contest `COMPLETED`.

We stamp it in the `contests` table, inside `ContestDatabase.update_contest` (the only writer of the `completed` flag), as `COALESCE(completed_at, now)` and only when the new status is `COMPLETED`. Stability is therefore a property of the write, not of any caller. `CANCELLED` contests are never stamped. Contests completed before the column existed stay unstamped and are never published as completed. The collector emits the stored value; the field is omitted otherwise.

This sits beside ADR-0007's "the object store is the source of truth" without contradicting it: the feed stays stateless about *snapshots*, but the contest database is already where completion is decided and is already read every cycle to select contests. It is contest state, not feed state.

A completed contest would otherwise never reach the feed, because selection filters on `completed=0`. `build_live_snapshot` therefore fills each sport with no live contest from `ContestDatabase.get_recently_completed_contest`, which applies the live-selection preference to `COMPLETED` contests whose `completed_at` is inside the **completion window** (18 hours). A live contest in the same sport always wins. `SportProcessor`, `CompletionProcessor` and `get_live_contest` are unchanged, so no sheet write or announcement runs for a completed contest.

## Considered options

- **Derive from the first `completed` snapshot in the manifest.** Keeps the database untouched, but every cycle walks manifests, and no snapshot is ever built for a completed contest without the selection change above, so it cannot work alone.
- **A DraftKings end time.** Nothing in the repository reads one, and it would couple the field to an undocumented upstream value.
- **Fallback through `SportProcessor.run`.** Rejected: it would re-run the destructive sheet write and bonus announcements for a finished contest.

## Consequences

- The window republishes near-identical snapshots each cycle until it closes. The window length is the knob.
- `completed_at` is the producer's observation time, so it lags DraftKings' actual end by up to one `CompletionProcessor` cycle.
- The `completed_at` column is added by `ContestDatabase.ensure_schema`, not by dfs-common's `init_schema`. `update_contests` therefore calls `ensure_schema` right after `init_schema`, so the completion job cannot write before the column exists even if `dkcontests` has not yet run on a legacy database.
- The feed path does not call `ensure_schema`. Until `update_contests` or `dkcontests` has run once on a legacy database, the feed's completed-contest fallback logs a SQLite error each cycle and publishes nothing for it. It self-heals after that first run.
