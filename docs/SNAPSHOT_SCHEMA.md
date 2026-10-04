# Snapshot schema 3: contest metrics

Producer-owned reference for the contest metrics in the schema-3 snapshot feed
(`services/snapshot_v3`). Terms (Game status, Non-cashing, Average salary
remaining) are defined in `docs/CONTEXT.md`.

This document covers the metrics the producer has defined so far. Later
metrics are added here as they ship.

## Machine-readable contract

The authority on the envelope's shape is the exported JSON Schema committed at
**`contract/snapshot.schema.json`** (a stable path consumers may pull at a
pinned commit). This document explains meaning, units and omission rules;
where the two disagree on shape, the schema wins.

The schema is generated from the pydantic models in
`src/dk_results/services/snapshot_v3/models/` (one module per contest section).
The feed validates every envelope against them before the hand-written
validator runs; a failure stops the build and nothing is uploaded. The schema
is never edited by hand; after changing the models, regenerate and commit it:

```bash
uv run python export_snapshot_schema.py
```

A test fails when the committed file is stale. In the models, optional fields
are omitted, never null; a field that may be null is required and typed
nullable (today only `contest.max_entries_per_user`). Sections not yet modelled
field by field accept any JSON object.

### Constraints the models enforce

Beyond field types, the models reject an envelope (and fail the build) when:

- a string the contract names (identity keys, `player_key`, `player_name`,
  VIP slot `slot`) is empty;
- a player name has leading or trailing whitespace. This covers every emitted
  player name: VIP `players_live[].player_name`, `players[].name`,
  `metrics.non_cashing.top_remaining_players[].player_name` and
  `metrics.threat.top_swing_players[].player_name`. (`players[]` is still a
  loose section, so only its `name` is checked);
- `metrics.non_cashing.users_not_cashing` is below 1;
- `metrics.distance_to_cash.per_vip` or `metrics.ownership_summary.per_vip` is
  empty (the metric is omitted instead);
- `metrics.non_cashing.top_remaining_players` has more than 10 rows;
- `contest.positions_paid` is below 1;
- `metrics.non_cashing.users_not_cashing` exceeds `max_entries` minus
  `positions_paid` (see below);
- a `cash_line` has neither cutoff, or lacks the cutoff its `cutoff_type`
  names;
- the `threat` field-remaining fields are not emitted together.

### Compatibility gate

CI compares the PR's committed schema with its base branch's
(`check_snapshot_schema_compat.py`, using only this repository's files) and
fails on a breaking change, naming each one by path and kind:

- `field_removed`: a declared field is gone. A rename is reported as the old
  name removed (the new name is an addition).
- `type_changed` / `type_narrowed`: a declared value's JSON type changed, or
  it accepts less than before: null dropped from a nullable field, a free
  string becoming an enum, or a constraint tightened. The `type_narrowed`
  detail names the keyword and `old -> new` (`none` when it was absent). The
  constraints are `minimum`, `exclusiveMinimum`, `minLength`, `minItems` and
  `minProperties` raised or newly added; `maximum`, `exclusiveMaximum`,
  `maxLength`, `maxItems` and `maxProperties` lowered or newly added; and a
  `pattern` added or changed. Regex containment is undecidable, so any new or
  different pattern counts; the gate is conservative here. Each type
  alternative is compared on its own, so `integer | null` with a raised
  `minimum` is caught.
- `became_required`: a declared optional field is now required.
- `became_optional`: a declared required field is now optional. This extends
  the spec's list on purpose: consumers generate TypeScript types from the
  schema, and `x: T` becoming `x?: T` breaks them.
- `enum_value_removed`: an enum (or `const`) lost a value.
- `branch_removed`: an object or array alternative of a union that the
  previous schema declared has no counterpart in the current one. Every
  alternative is compared, not only the first. Object branches pair by
  discriminator (the properties whose schema is a `const`, matched on value, so
  reordering branches is not a change); branches without one, and array
  branches, pair by position among the branches of that type, an array branch
  by the discriminator of its object items when it has one. A lone branch
  always pairs with the current one, so a changed `const` there is
  `enum_value_removed`.

Not breaking: additions (a new field, required or optional, a new section, a
new union branch, a new enum value), title and description edits, a loosened or
removed limit, a removed `pattern`, and **declaring what was left open**. A loose section (one that
"accepts any JSON object") is a placeholder that promises nothing about its
contents, so tightening it to typed fields, as the per-section porting PRs
do, passes the gate, as does giving an untyped value a type and limits. The gate guards what the previous
schema declared, so tightening an already declared field, such as dropping
null from `contest.max_entries_per_user` or adding a `minLength` to a typed
string, is breaking.

To ship a breaking change deliberately, label the PR `breaking-change` and add
an entry to the [Breaking changes](#breaking-changes) log in the same PR; the
gate then passes only if every breaking path it reports is named by an entry
the log gained in the PR (entries already on the base branch don't count). To
run the gate locally
against `main`:

```bash
git show origin/main:contract/snapshot.schema.json > /tmp/base.schema.json
uv run python check_snapshot_schema_compat.py --base /tmp/base.schema.json
```

The gate compares shapes, not meaning: a field that keeps its name and type
but changes meaning passes. The prose here and the golden envelope diffs are
the guard for that.

## Rules that apply to every metric

- **Omit, never null.** A metric or field that cannot be computed is absent.
  Absence is the only "not provided" signal; no metric is ever emitted with
  null fields.
- **Percentages** are percentage points (`62.5` means 62.5%), rounded to two
  decimals. Salaries are DraftKings dollars (`6543.22`), rounded to two
  decimals.
- **Game status** is classified by one shared classifier
  (`analytics/game_status.py`). Status text is normalized first, so
  `In-Progress` and `In Progress` match.

  | Game status | Remaining | In play |
  |---|---|---|
  | In-Progress, Delayed, Suspended | yes | yes |
  | Matchup text (pre-game; contains `@`) | yes | no |
  | Explicit locked slot (player hidden) | yes | no |
  | Final, Postponed, Cancelled / Canceled | no | no |
  | anything else (including golf's tournament name) | unknown | unknown |

- **A sport has no Game status** when no player in its pool classifies as
  anything but unknown (today: golf). This is detected from
  `players[].game_status`, not from a list of sport names. Ownership remaining
  in standings and the ownership watchlist, top remaining and swing players,
  average salary remaining, field remaining, leverage, and ownership in play
  are omitted for such a pool. VIP total ownership and computable non-cashing
  count/average PMR remain available. Remaining salary (a user's cap minus
  revealed salaries) and train detection retain their separate meanings.

## `contest.positions_paid`

| | |
|---|---|
| Type | integer, at least 1, optional |
| Location | `sports.<sport>.contests[0]` |
| Meaning | The number of paid positions: the last rank DraftKings pays. |

Omitted when DraftKings reports no payout positions. It bounds the non-cashing
count (see `contest.metrics.non_cashing`).

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
`docs/CONTEXT.md`.

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

## VIP lineup rows

Each `contest.vip_lineups[]` row carries the VIP's identity (`display_name`,
`entry_key`, `vip_entry_key`) and these figures, which are present for every
tracked VIP the source reports them for, including VIPs ranked below the
standings limit:

| Field | Type | Meaning |
|---|---|---|
| `rank` | integer, optional | The VIP's current contest rank. |
| `points` | number, optional | The VIP's current fantasy points. |
| `pmr` | number, optional | The VIP's minutes remaining (PMR). |

A figure that cannot be parsed is omitted, never emitted as null or a string.
Player names on every emitted row have no leading or trailing whitespace.

## VIP lineup slots

Each `contest.vip_lineups[]` row may include `players_live`, the lineup's
slots in DraftKings roster order. Every row carries `slot`, the roster
position (never empty). A revealed player also carries its existing `player_name`,
`player_key` when resolvable, optional `salary`, and `is_live` fields.

A player DraftKings has not revealed is represented as a locked slot:
`{slot, player_name: "LOCKED 🔒", is_locked: true}`. Locked rows omit
`player_key`, `salary`, and `is_live`; they do not identify a player, add to
swing-player VIP counts, or enter the validator's known-player key set.

## `contest.metrics.ownership_summary`

| Field | Type | Meaning |
|---|---|---|
| `source` | string | Always `vip_lineup_players`. |
| `scope` | string | Always `vip_lineup`. |
| `per_vip` | array | One row per tracked VIP entered in the contest, ordered by `vip_entry_key`. |

Each `per_vip` row:

| Field | Type | Meaning |
|---|---|---|
| `vip_entry_key` | string | The VIP's entry key. |
| `entry_key` | string, optional | The VIP's standings entry key. Absent when it could not be resolved. |
| `display_name` | string, optional | The VIP's display name. Absent when unknown. |
| `total_ownership_pct` | number | Ownership summed over every lineup slot, in percentage points, two decimals. |
| `ownership_in_play_pct` | number, optional | Ownership summed over slots whose Game status is in play (In-Progress, Delayed, Suspended), two decimals. Pre-game and finished players are excluded, so this differs from ownership remaining. |
| `is_partial` | boolean | True when the numbers may be incomplete: see below. Always present. |

Each slot's ownership and Game status come from the contest's `players[]`,
looked up by the slot's `player_key`. VIP slot rows carry neither value, so
`players[]` stays the single source of both.

`is_partial` is true when any slot is explicitly locked (`is_locked: true`),
has no matching `player_key` in `players[]` (or the matched player has no
ownership), or has an unrecognized Game status. A locked or unmatched slot
adds nothing to either sum. An unrecognized status still counts toward
`total_ownership_pct` but not toward `ownership_in_play_pct`. Unknown status
sets `is_partial` for golf-like pools too, even though golf omits
`ownership_in_play_pct`.

Omitted when:

- no tracked VIP is entered (`vip_lineups` is empty), or no entered VIP has
  an entry key and lineup slots. The whole metric is absent, not an empty `per_vip`.

Omitted per row when:

- the sport has no Game status (golf): `ownership_in_play_pct` is absent and
  `total_ownership_pct` is still emitted.

The pre-v3 `ownership_in_play_source` field is not emitted. **Behavior change
from pre-v3:** the old producer counted pre-game players as in play; they are
now excluded.

## Breaking changes

Every deliberate breaking change to `contract/snapshot.schema.json`, newest
first. Each entry is one top-level bullet: the date, the PR, each path and
kind the gate reported, and the migration a consumer needs. A PR labeled
`breaking-change` passes the compatibility gate only when entries it adds here
name every path the gate reports.

No breaking changes yet.
