# Snapshot schema 3: contest metrics

Producer-owned reference for the contest metrics in the schema-3 snapshot feed
(`services/snapshot_v3`). Terms (Game status, Non-cashing, Average salary
remaining) are defined in `docs/CONTEXT.md`.

This document covers the metrics the producer has defined so far. Later
metrics are added here as they ship.

## Machine-readable contract

The authority on the envelope's shape is the pydantic models in
`src/dk_results/services/snapshot_v3/models/` (one module per contest section).
The feed validates every envelope against them before the hand-written
validator runs; a failure stops the build and nothing is uploaded.

Their JSON Schema is committed at **`contract/snapshot.schema.json`** (a stable
path consumers may pull at a pinned commit). It is generated, never edited by
hand; after changing the models, regenerate and commit it:

```bash
uv run python export_snapshot_schema.py
```

A test fails when the committed file is stale. In the models, optional fields
are omitted, never null; a field that may be null is required and typed
nullable (today only `contest.max_entries_per_user`). Sections not yet modelled
field by field accept any JSON object.

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
position. A revealed player also carries its existing `player_name`,
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
