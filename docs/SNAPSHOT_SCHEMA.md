# Snapshot schema 3: contest metrics

Producer-owned reference for the contest metrics in the schema-3 snapshot feed
(`services/snapshot_v3`). Terms (Game status, Non-cashing, Average salary
remaining) are defined in `docs/CONTEXT.md`.

This document covers the metrics the producer has defined so far. Later
metrics are added here as they ship.

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
  | Final, Postponed, Cancelled / Canceled | no | no |
  | anything else (including golf's tournament name) | unknown | unknown |

- **A sport has no Game status** when no player in its pool classifies as
  anything but unknown (today: golf). This is detected from
  `players[].game_status`, not from a list of sport names. Metrics that depend
  on "remaining" are omitted for such a sport.

## `contest.live_metrics.avg_salary_per_player_remaining`

| | |
|---|---|
| Type | number (DraftKings dollars, two decimals) |
| Location | `sports.<sport>.contests[0].live_metrics` |
| Meaning | Mean salary over every entry's unfinished lineup slots across the whole contest, weighted by slot. A contest-level figure, not per VIP. A slot is unfinished unless its player's Game status is Final, Postponed or Cancelled; players with an unrecognized status count as unfinished. |

Present for any live primary contest, whether or not any tracked VIP is entered.

Omitted when:

- every lineup slot is finished (nothing to average), or
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
when every held player is finished.

The whole metric is omitted when no entry is below the cash line or the
non-cashing figures are unavailable. It is emitted for sports with no Game
status (golf) because it does not depend on per-player status.

The Google Sheet's non-cashing block is produced separately and is unaffected
by this metric.
