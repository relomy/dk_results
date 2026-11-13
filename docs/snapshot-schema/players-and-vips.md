# Snapshot schema 3: players and VIPs

Player-pool and VIP sections split out of [`docs/SNAPSHOT_SCHEMA.md`](../SNAPSHOT_SCHEMA.md),
which holds the contract, constraints, compatibility gate, rules that apply to
every metric and the Breaking changes log. Terms are defined in `GLOSSARY.md`.

## Contest player pool: Scorecard fields

`players[]` rows gain optional fields taken from the tracked VIPs'
**Scorecards** (DraftKings' per-entry roster readout; see the glossary). A
Scorecard is fetched per entry, but these are facts about the player, identical
whichever entry holds them, so they live on the pool row the dashboard already
joins lineup rows to, not on each VIP slot. They reuse the Scorecards already
fetched each cycle; there are no extra requests.

| Field | Type | Meaning |
|---|---|---|
| `rt_projection` | number, optional | The player's current real-time projected points, as DraftKings sends it (not rounded; the Google Sheet keeps a two-decimal string). `0` is a real projection and is emitted. |
| `stats_text` | string, optional | DraftKings' one-line stat summary for the player (for example "1 PaTD, 286 PaYds, 5 RuYds"). |
| `time_remaining_minutes` | number, optional | The player's **PMR** (minutes remaining). Emitted only when the Scorecard labels the unit as PMR. `0` means their game is finished and is emitted, so "done" is distinct from "unknown" (omitted). |
| `value_icon` | `fire` or `ice`, optional | DraftKings' hot / cold value marker. |

Each is omitted, never null, when DraftKings does not supply it. An empty,
missing, unparseable or unrecognised value is omitted (so a new DraftKings icon cannot fail
validation). A pool player no tracked VIP holds, a locked slot, a Scorecard row
without an id, and a row whose id matches no pool player get none of the fields.

When several VIPs hold the same player, Scorecards are read in ascending VIP
entry key order and the first non-empty value per field wins, independent of
fetch order.

**Provenance of a pool row.** Name, position, roster positions, salary, team and
`game_status` come from the salary data; `ownership_pct`, `fantasy_points` and
`value` from standings; `matchup` from draftables (matched by draftable id);
the Scorecard fields from the VIP Scorecards, matched by draftable id. The
draftable id is a join key only and is not emitted.

**Limitation (Showdown).** A pool row stands for one draftable. A Scorecard row
for a different draftable of the same player (a Captain versus Flex of one
Showdown player, whose projections differ) does not match and is omitted.

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

The rows are ordered by `rank` ascending, then `vip_entry_key`, then
`display_name` (both compared as text); a row without a `rank` or
`vip_entry_key` sorts after the rows that have one. The order is the same on
every run for the same contest state, regardless of the order in which VIP
lineups were fetched.

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

