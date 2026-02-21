# Google Sheet Feature Set and Dashboard Parity

This document captures the current Google Sheet live feature set and how `dk_results` should expose canonical data for `dk_dashboard` parity.

Companion design doc (local planning artifact, not repo-portable):
- `2026-02-21-google-sheet-parity-to-dashboard-design.md` (stored in local Codex plans directory)

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
- Covered now: player standings core table, distance-to-cash, threat/leverage baseline, train ranking/top-N.
- Partial: VIP player-level row detail, ownership summary split (total vs in-play), non-cashing summary promotion.
- Known caveat: payout fields are often null in live flow; live cashing should be metrics-derived when distance-to-cash metrics are present.

## Recommended Next Contract Additions
1. `contest.vip_lineups[].players_live[]` for full VIP per-player stats.
2. `contest.metrics.ownership_summary` with explicit total/in-play percentages and scope.
3. `contest.metrics.non_cashing` with users_not_cashing and avg_pmr_remaining.
4. Contest metadata normalization (`state`, `contest_type`, `entry_fee_cents`, `prize_pool_cents`, etc.).

## Delivery Approach
1. Parity tranche: add missing fields, render sheet-equivalent panels.
2. Stabilization tranche: contract/type/doc reconciliation and compatibility tests.
3. Superset tranche: trends, decision cards, alerts, manifest-driven recaps.

## Contract Guardrails (Authoritative)
1. Cashing precedence:
   - Use `contest.metrics.distance_to_cash.per_vip` as live truth when a row exists for the VIP.
   - Fallback to payout presence only when that metrics row is unavailable.
2. Ownership precedence:
   - `contest.ownership_watchlist` remains canonical threat source.
   - `contest.metrics.ownership_summary` is derived from that same source and must declare scope/source.
3. `players_live[]` typing:
   - Define units and nullability explicitly (percent values, numeric salary/points/value/projection, raw display strings where needed).
4. Validation timing:
   - Producer/consumer contract tests are part of parity tranche gate, not a later cleanup.
5. Versioning:
   - Additive changes remain in schema v2.
   - Semantic-breaking cleanup requires schema v3 planning.
