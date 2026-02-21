# Google Sheet Feature Set and Dashboard Parity

This document captures the current Google Sheet live feature set and how `dk_results` should expose canonical data for `dk_dashboard` parity.

Planning and implementation artifacts are maintained in repo docs and branch history; this file tracks the stable feature-level parity baseline.

## Feature Set (from current sheet)
1. Player ownership standings (position, name, team, matchup, salary, ownership, points, value).
2. VIP lineup blocks with per-player live stats (own/salary/pts/value/rt proj/time/stats).
3. Total ownership and ownership in play.
4. Cashing info with contest name/cutoff context.
5. Non-cashing summary (users not cashing, avg PMR remaining, top 10 ownership remaining).
6. Train finder clusters.

## Parity Direction
- Keep React thin and contract-driven.
- Prefer additive exporter fields over dashboard inference.
- Preserve deterministic semantics:
  - missing object = unavailable
  - present but empty = empty state

## Current Coverage Summary
- Covered now (schema v2 + additive metrics):
  - player standings fields for parity columns (`position`, `matchup`, `salary`, `ownership_pct`, `fantasy_points`, `value`, status)
  - distance-to-cash metrics (`contest.metrics.distance_to_cash`)
  - threat/leverage metrics (`contest.metrics.threat`)
  - train ranking/top-N metrics (`contest.metrics.trains`)
  - VIP player-level row detail (`vip_lineups[].players_live[]`)
  - ownership summary split (`contest.metrics.ownership_summary`)
  - non-cashing summary (`contest.metrics.non_cashing`)
- Live cashing caveat remains:
  - payout fields may be null in active contests, so consumers should prefer distance-to-cash metrics when present.

## Shipped Contract Additions (Schema v2)
1. `contest.vip_lineups[].players_live[]` for VIP per-player live stats rows.
2. `contest.metrics.ownership_summary` for per-VIP total/in-play ownership summary.
3. `contest.metrics.non_cashing` for users-not-cashing and PMR/top-remaining summaries.
4. Stable per-VIP keying support (`vip_entry_key` additive, fallback `entry_key`) for deterministic consumer joins.

## Delivery Approach
1. Parity tranche: complete (fields and metrics needed for sheet-equivalent panels are exported).
2. Stabilization tranche: continue contract/type/doc reconciliation and compatibility tests.
3. Superset tranche: trends, decision cards, alerts, manifest-driven recaps.

## Contract Guardrails (Authoritative)
1. Cashing precedence:
   - Use `contest.metrics.distance_to_cash.per_vip` as live truth when a row exists for the VIP.
   - Fallback to payout presence only when that metrics row is unavailable.
2. Ownership precedence:
   - `contest.ownership_watchlist` remains canonical threat source.
   - `contest.metrics.ownership_summary` is derived from `vip_lineups[].players_live` and must declare scope/source (`vip_lineup_players` / `vip_lineup`).
3. `players_live[]` typing:
   - Define units and nullability explicitly (percent values, numeric salary/points/value/projection, raw display strings where needed).
4. Validation timing:
   - Producer/consumer contract tests are part of parity tranche gate, not a later cleanup.
5. Versioning:
   - Additive changes remain in schema v2.
   - Semantic-breaking cleanup requires schema v3 planning.
