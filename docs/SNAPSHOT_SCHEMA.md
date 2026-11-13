# Snapshot schema 3: contest metrics

Producer-owned reference for the contest metrics in the schema-3 snapshot feed
(`services/snapshot_v3`). Terms (Game status, Non-cashing, Average salary
remaining) are defined in `GLOSSARY.md`.

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
validator runs; a failure stops the build and nothing is uploaded. Presence
rules run last and only record [`presence_warnings`](#presence_warnings). The schema
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
  `metrics.threat.top_swing_players[].player_name`. (`players[]` is still mostly a
  loose section: only its `name` and the Scorecard fields are checked);
- `metrics.non_cashing.users_not_cashing` is below 1;
- `metrics.distance_to_cash.per_vip` or `metrics.ownership_summary.per_vip` is
  empty (the metric is omitted instead);
- `metrics.non_cashing.top_remaining_players` has more than 10 rows;
- `contest.positions_paid` is below 1;
- `contest.completed_at` is present but not a valid ISO timestamp (the validator
  also rejects `null`);
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

## `producer_commit`

| | |
|---|---|
| Type | string or `null`, required: a full 40-character lowercase hex SHA |
| Location | the envelope's top level |
| Meaning | The dk_results commit that built the snapshot: the **producer commit**. |

The snapshot feed resolves it once per run: `DK_RESULTS_COMMIT` when set to a
valid SHA (for deploys without git metadata), otherwise `git rev-parse HEAD` in
the producer's checkout. The key is always present and is `null`, never omitted,
when the commit cannot be told: git is unavailable or fails, or the checkout has
uncommitted changes to tracked files (a snapshot built from edited code was not
built by that commit). Callers that build an envelope without passing a commit
also get `null`. The day manifest does not carry it. Adding it is an additive
change.

The goldens in `contract/goldens/` carry the fixed placeholder
`0123456789abcdef0123456789abcdef01234567`.

## Per-metric reference

The remaining sections live in `docs/snapshot-schema/`:

- [Contest metrics](snapshot-schema/contest-metrics.md): `contest.positions_paid`,
  `contest.completed_at`, `cash_line`, `distance_to_cash`,
  `avg_salary_per_player_remaining`, `non_cashing` and `threat`.
- [Players and VIPs](snapshot-schema/players-and-vips.md): Scorecard fields on
  `players[]`, VIP lineup rows and slots, and `ownership_summary`.

## `presence_warnings`

A required top-level list of the presence rules the snapshot broke; `[]` when
none did. Each item is `{"path", "rule"}`: `path` is the dotted path of the blank
field (the same form the validator's messages use, e.g.
`sports.mlb.players[4].stats_text`) and `rule` is the rule id below. One item per
blank field.

Presence rules are strict before merge and soft at runtime (ADR-0016). The
goldens test fails when any golden carries a warning, so a code bug that leaves
a field blank is caught before merge. At runtime a broken rule never stops
a snapshot from publishing: it is recorded here, because some blanks come from
DraftKings. Shape and type checks (the contract models and the hand-written
validator) are unchanged and still block publishing. Build order: shape check,
hand-written validator, then the presence rules.

| Rule id | Condition | Field expected filled |
|---|---|---|
| `cashing_row_has_payout` | a `contest.standings[]` row has `is_cashing: true` | that row's `payout_cents` is a number, not null |
| `unlocked_vip_slot_has_player_key` | a `contest.vip_lineups[].players_live[]` slot is not locked (`is_locked` is not `true`) | the slot's `player_key` |
| `in_progress_player_has_stats` | a `players[]` row's Game status is in play (`In Progress`, `Delayed` or `Suspended`) | the row's `stats_text` and `rt_projection`, one warning each |

These stay unruled because their blanks are legitimate: `vip_lineups`,
`train_clusters`, golf `team`, `is_locked`, `time_remaining_minutes`,
`value_icon`.

## Breaking changes

Every deliberate breaking change to `contract/snapshot.schema.json`, newest
first. Each entry is one top-level bullet: the date, the PR, each path and
kind the gate reported, and the migration a consumer needs. A PR labeled
`breaking-change` passes the compatibility gate only when entries it adds here
name every path the gate reports.

No breaking changes yet.
