# Snapshot schema 3: contest metrics (per-metric reference)

Per-metric sections split out of [`docs/SNAPSHOT_SCHEMA.md`](../SNAPSHOT_SCHEMA.md),
which holds the contract, constraints, compatibility gate, rules that apply to
every metric and the Breaking changes log. Terms are defined in `GLOSSARY.md`.

## `contest.positions_paid`

| | |
|---|---|
| Type | integer, at least 1, optional |
| Location | `sports.<sport>.contests[0]` |
| Meaning | The number of paid positions: the last rank DraftKings pays. |

Omitted when DraftKings reports no payout positions. It bounds the non-cashing
count (see `contest.metrics.non_cashing`).

## `contest.completed_at`

| | |
|---|---|
| Type | string, optional: ISO-8601 UTC in the `snapshot_at` format (`YYYY-MM-DDTHH:MM:SSZ`) |
| Location | `sports.<sport>.contests[0]` |
| Meaning | The moment the producer first observed DraftKings reporting the contest `COMPLETED`. |

`completed_at` is the producer's **observation time**, not DraftKings' end time:
it lags the real end by up to one `CompletionProcessor` cycle, so do not trust it
beyond that precision. It is stamped once, read from the contest database, and is
identical on every later snapshot of the same contest, so it is safe to order
completed contests by it.

The key is **omitted, never null**, for contests that are not completed,
cancelled contests, and contests that completed before the stamp was recorded.
Adding it is an additive change.

## `contest.live_metrics.cash_line`

| Field | Type | Meaning |
|---|---|---|
| `cutoff_type` | string | `rank`, `points` or `unknown`. |
| `rank_cutoff` | integer, optional | The last paid rank seen in the standings. |
| `points_cutoff` | number, optional | The points total at the cash line. |

A cutoff the producer could not determine is **omitted, never null**. A cash
line with neither cutoff is not emitted, and `cutoff_type` `rank` or `points`
always comes with its own cutoff.

## `contest.metrics.distance_to_cash`

| Field | Type | Meaning |
|---|---|---|
| `per_vip` | array | One row per tracked VIP with known points, ordered by `vip_entry_key`. Never empty: with no row the whole metric is omitted. |
| `cutoff_points` | number, optional | The cash line's points total. |

Each `per_vip` row:

| Field | Type | Meaning |
|---|---|---|
| `vip_entry_key` | string, optional | The VIP's tracking key. |
| `entry_key` | string, optional | The VIP's standings entry key. |
| `display_name` | string, optional | The VIP's display name. |
| `points_delta` | number | The VIP's points minus the cash line's points; positive means inside the money. |
| `rank_delta` | integer, optional | The cash line's rank cutoff minus the VIP's rank; omitted when either is unknown. |

An identity key the VIP lacks is **omitted from the row, never null**.

## `contest.live_metrics.avg_salary_per_player_remaining`

| | |
|---|---|
| Type | number (DraftKings dollars, two decimals) |
| Location | `sports.<sport>.contests[0].live_metrics` |
| Meaning | Mean salary over every entry's unfinished slots whose player and salary are known, across the whole contest, weighted by slot. Locked slots are excluded because their salaries are hidden; no salary partial flag is emitted. A contest-level figure, not per VIP. A slot is unfinished unless its player's Game status is Final, Postponed, Cancelled or Canceled; players with an unrecognized status count as unfinished. |

Present for any live primary contest, whether or not any tracked VIP is entered.

Omitted when:

- no unfinished slot has a known player and salary (nothing to average), or
- the sport has no Game status (golf).

## `contest.metrics.non_cashing`

| Field | Type | Meaning |
|---|---|---|
| `users_not_cashing` | integer | Count of standings rows ranked below the cash line, as of the last standings parse. Always at least 1. |
| `avg_pmr_remaining` | number | Mean PMR (players minutes remaining) across those rows, two decimals. |
| `top_remaining_players` | array, optional | Up to 10 `{player_name, ownership_remaining_pct}` rows, highest first. `ownership_remaining_pct` is the share of non-cashing entries (percentage points) still holding that unfinished player. |

`top_remaining_players` appears only for sports that tally it: NFL,
NFLShowdown, CFB and NBA. For any other sport (for example MLB) the key is
absent, not an empty list. For a tallied sport it is a list and may be empty
when every held player is finished. It is omitted for any pool without Game status,
even when the sport normally tallies it. Snapshot rows exclude all finished statuses
using the shared classifier; the Google Sheet's separate tally is unchanged.

`users_not_cashing` can never exceed the entries beyond the paid positions:
`max_entries` minus `contest.positions_paid`. The envelope carries no separate
entry count, so `max_entries` (never below the real entry count) stands in for
it, which only loosens the bound. The check is skipped when `positions_paid` is
absent.

The whole metric is omitted when no entry is below the cash line or the
non-cashing figures are unavailable. It is emitted for sports with no Game
status (golf) because it does not depend on per-player status.

The Google Sheet's non-cashing block is produced separately and is unaffected
by this metric.

## `contest.metrics.threat`: field remaining and VIP-vs-field leverage

`threat` is emitted when **any** of its parts is present: `top_swing_players`,
the field-remaining fields, or `vip_vs_field_leverage`. A sport with no top
swing players (for example MLB) still gets `threat` when field remaining is
available. Terms (Field remaining, Uniqueness delta) are defined in
`GLOSSARY.md`.

### Field remaining

| Field | Type | Meaning |
|---|---|---|
| `leverage_semantics` | string | Always `"positive=unique"`: a positive uniqueness delta means the VIP is more unique than the field. |
| `field_remaining_scope` | string | Always `"contest_field"`: the number covers every standings row in the contest, not the tracked VIPs. |
| `field_remaining_source` | string | Always `"contest_standings_mean"`. |
| `field_remaining_pct` | number | Mean ownership remaining (percentage points, two decimals) over the **full, pre-truncation** standings, not the truncated `standings` list and not the watchlist. Ownership remaining uses the shared Game status classifier. |
| `field_remaining_is_partial` | boolean | True when any standings entry was excluded from the mean (its lineup is missing or empty), or any included lineup contains a locked or unresolved slot with unavailable ownership. Always emitted next to `field_remaining_pct`; covers the full contest field before truncation. |

Present for any live primary contest, whether or not any tracked VIP is
entered. The five fields are emitted together or not at all. They are omitted
when:

- the sport has no Game status (golf), or
- no standings row had a resolvable lineup, so there is no mean.

### `vip_vs_field_leverage[]`

One row per tracked VIP:

| Field | Type | Meaning |
|---|---|---|
| `vip_entry_key` | string | The VIP's tracking key. |
| `entry_key` | string | The VIP's contest entry key. |
| `display_name` | string | The VIP's display name. |
| `vip_remaining_pct` | number | Ownership remaining on the VIP's own standings row, matched to the VIP by `entry_key`. |
| `field_remaining_pct` | number | The same value as the `threat` field of that name. |
| `uniqueness_delta_pct` | number | The rounded `field_remaining_pct` minus the rounded `vip_remaining_pct`, rounded to two decimals, in percentage points. Positive means the VIP is more unique than the field. |
| `is_partial` | boolean | Required on every row. True when this VIP's own standings lineup contains a locked or unresolved slot with unavailable ownership. A complete VIP's flag remains false when another entry makes the field partial. |

`vip_remaining_pct` is read from the full, pre-truncation standings, so a VIP
ranked below the standings limit still gets a row. A VIP with no matching
standings row (or one with no resolvable lineup) is omitted from the list,
never emitted with nulls. The list is absent when no tracked VIP is entered, when no
VIP matches, or whenever the field-remaining fields are omitted (golf).

