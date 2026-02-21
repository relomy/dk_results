# dk_results Feature Specification

Date: 2026-02-21
Status: Draft (source-of-truth feature definition)

## Purpose
`dk_results` is the production data and operations engine for DFS live tracking. It ingests DraftKings contest data, computes live analytics, updates Google Sheets, and publishes canonical snapshot artifacts for downstream consumers.

This document defines product features of `dk_results` independent of any single consumer UI.

## Product Surfaces
1. Google Sheets output (live operating surface).
2. Canonical snapshot artifacts from exporter flows (`export_fixture.py` bundle/single + publish):
   - canonical snapshot envelope
   - `latest.json`
   - UTC-day manifests
3. `db_main --snapshot-out` compatibility snapshot envelope (legacy/raw sport payload shape).
4. Discord notifications (contest lifecycle + VIP bonus signals).
5. CLI/runtime jobs for scheduled operation.

## Core Domain Entities
1. Contest: selected live contest per sport plus metadata/state.
2. Player: salary + live ownership/points/value state.
3. Entry/User: standings row with rank/points/PMR/lineup context.
4. VIP lineup: per-VIP roster and live scorecard fields.
5. Train cluster: lineup clusters by shared train criteria.

## Canonical Semantics
1. Determinism (run-scoped): within a single run, normalization/sorting rules are deterministic for derived sections.
2. Timestamp behavior: top-level generated timestamps are runtime-generated and therefore not replay-identical across runs.
3. Missing vs empty:
   - Missing object => unavailable.
   - Present object with empty collections => empty state.
4. No silent approximation: when source data is insufficient, omit or null fields rather than infer.
5. Cashing precedence:
   - if `contest.metrics.distance_to_cash.per_vip` has an entry for a VIP, derive live cashing from metrics (`points_delta`, fallback `rank_delta`)
   - otherwise fallback to payout presence (`payout_cents != null`)
6. Ownership precedence:
   - `ownership_watchlist` is the canonical source for threat/leverage computations
   - any ownership summary metrics must declare source/scope and be derived from the same authoritative source
7. Additive evolution: new fields are additive unless explicit schema-breaking version bump is planned.

## Feature Set

### F1. Contest Selection and State Intelligence
Goal:
- Identify the primary live contest per sport with deterministic selection logic.

Inputs:
- Contest DB rows.
- Sport-specific selection parameters (minimum entry fee, keyword, tie-breakers).
- Optional explicit contest id.

Computation:
- Select live contest by sport-specific criteria and deterministic tie-break ordering.
- Maintain contest status/completion updates from contest detail polling.

Outputs:
- Selected contest identifiers and selection-reason metadata.
- Contest status/state updates persisted in DB and available for downstream outputs.

Unavailable conditions:
- If no eligible live contest exists, sport output is unavailable for live contest selection.

### F2. Live Data Ingestion Pipeline
Goal:
- Acquire all live source inputs needed for analysis and publishing.

Inputs:
- Salary CSV (by draft group).
- Full standings CSV export.
- VIP scorecard/lineup endpoints.
- VIP roster configuration (`vips.yaml`).

Computation:
- Parse salary + standings rows into normalized `Results`, `Player`, and `User` objects.
- Fetch VIP lineup details keyed by VIP entry membership.

Outputs:
- In-memory normalized contest dataset used by sheet writer and snapshot builder.

Unavailable conditions:
- If standings export fails, contest analytics depending on standings are unavailable.
- If VIP config absent/empty, VIP-derived features are empty/unavailable as appropriate.

### F3. Player Ownership Standings Analytics
Goal:
- Provide sortable player-level live board metrics.

Inputs:
- Parsed players from salary + standings player stats.

Computation:
- Calculate/normalize per-player ownership, points, value, matchup/game status.
- Preserve deterministic player ordering for outputs.

Outputs:
- Sheet player standings table.
- Snapshot player pool section with live player metrics.

Unavailable conditions:
- Player live stat columns unavailable if standings player-stat rows are missing.

### F4. VIP Lineup Intelligence
Goal:
- Provide VIP-specific lineup and live performance detail.

Inputs:
- VIP user list.
- VIP entry keys from standings membership.
- VIP scorecard roster payloads.

Computation:
- Resolve VIP lineups and lineup slots in source order.
- Normalize per-lineup live fields (points/rank/PMR/remaining ownership).
- Preserve stable VIP identifiers where available.

Outputs:
- Sheet VIP lineup blocks.
- Snapshot VIP lineup structures and live subfields.

Unavailable conditions:
- If scorecards are inaccessible, VIP lineup detail is unavailable.

### F5. Cash-Line and Distance-to-Cash Analytics
Goal:
- Quantify lineup distance to the contest cash threshold.

Inputs:
- Positions paid / cash cutoff context.
- Current lineup points and rank.

Computation:
- Compute cash-line cutoffs.
- Compute points and rank deltas against cash line using deterministic sign conventions.

Outputs:
- Cash-line metrics in contest live metrics.
- Per-VIP distance-to-cash metrics when computable.

Unavailable conditions:
- If required cutoff and lineup fields are missing, omit non-computable deltas.

### F6. Ownership Pressure and Threat Analytics
Goal:
- Surface where field ownership pressure can swing outcomes.

Inputs:
- Ownership watchlist (remaining ownership by player).
- VIP remaining ownership and roster composition.

Computation:
- Compute field remaining totals from authoritative source when present.
- Compute partial sums when only entry-level values are present, flagging partiality.
- Compute VIP counts on swing players via lineup name matching.
- Compute uniqueness/leverage deltas with fixed sign semantics.

Outputs:
- Threat/swing player metrics.
- VIP-vs-field leverage metrics.

Unavailable conditions:
- If watchlist object is missing, threat metrics unavailable.

### F7. Non-Cashing Cohort Analytics
Goal:
- Track composition and pressure among entries currently below cash line.

Inputs:
- Standings users + parsed lineup players.

Computation:
- Count non-cashing users.
- Compute non-cashing average PMR.
- Rank top remaining players by non-cashing concentration.

Outputs:
- Sheet non-cashing info panel.
- Snapshot ownership/non-cashing fields (current and/or metrics block as contract evolves).

Unavailable conditions:
- If non-cashing cohort cannot be derived from standings, section is unavailable.

### F8. Train Finder and Cluster Ranking
Goal:
- Identify concentrated lineup clusters (“trains”) with meaningful rank/size context.

Inputs:
- User lineup states and salary-remaining constraints.

Computation:
- Build clusters from deterministic train criteria.
- Rank clusters with deterministic tie-breakers.
- Optionally produce recommended top-N pre-slice.

Outputs:
- Sheet train finder panel.
- Snapshot train cluster raw section + metrics ranking/top list.

Unavailable conditions:
- If train source set is missing/empty, clusters are empty/unavailable per section presence rules.

### F9. Google Sheets Publishing
Goal:
- Publish live operational views for each sport tab.

Inputs:
- Results/analytics outputs from features F1-F8.

Computation:
- Write deterministic ranges for players, VIPs, contest/cash info, non-cashing info, and trains.

Outputs:
- Updated Google Sheet sport tabs and ancillary blocks.

Unavailable conditions:
- If sheet credentials/config are missing, publishing fails fast.

### F10. Canonical Snapshot and Publishing Artifacts
Goal:
- Produce canonical machine-consumable artifacts for downstream systems via exporter flows.

Inputs:
- Feature outputs from F1-F8.

Computation:
- Build normalized snapshot envelope with canonical contract fields.
- Validate canonical constraints.
- Publish `latest.json` and UTC-day manifest entries deterministically.

Outputs:
- Snapshot envelope JSON.
- `latest.json`.
- `manifest/YYYY-MM-DD.json`.

Unavailable conditions:
- Exporter canonical commands fail if required envelope metadata is missing/invalid.

### F10b. `db_main --snapshot-out` Compatibility Snapshot
Goal:
- Emit a multi-sport snapshot envelope from the scheduled sheet pipeline for integration/testing compatibility.

Inputs:
- Selected contests processed by `db_main`.
- Per-sport snapshots built via `build_snapshot` and normalized.

Computation:
- Build envelope with schema_version/snapshot timestamps and normalized raw per-sport payloads.
- Write output when `--snapshot-out` is provided.

Outputs:
- Compatibility snapshot envelope written to the configured output path.

Notes:
- This payload shape is not the canonical exporter contract shape used by `export_fixture.py` bundle/single outputs.
- Consumers requiring canonical contract guarantees should use exporter commands.

Unavailable conditions:
- If no contests are selected/processed, emitted payload may be partial/empty by sport rather than hard-failing.

### F11. Operational Notifications
Goal:
- Notify operators of contest lifecycle transitions and VIP bonus opportunities.

Inputs:
- Contest state transitions.
- VIP lineup bonus signal parsing.
- Notification de-duplication state.

Computation:
- Emit warning/live/completed contest notifications with dedupe controls.
- Emit VIP bonus messages on positive transitions.

Outputs:
- Discord/webhook notifications.

Unavailable conditions:
- If notifications disabled or webhook unset, outputs are intentionally suppressed.

## CLI Entry Points
1. `db_main.py`
- Primary scheduled flow: select contests, ingest data, compute analytics, write sheets.
- Optional snapshot envelope emission (`--snapshot-out`).

2. `export_fixture.py`
- Single sport snapshot export.
- Multi-sport bundle export.
- Publish helper for `latest.json` + manifest from existing snapshot.

3. `update_contests.py`
- Contest status completion updater + lifecycle notifications.

4. `find_new_double_ups.py`
- Lobby polling and contest discovery/insert notifications.

## Data Quality and Determinism Requirements
1. Stable sorting for lists exposed in snapshot artifacts.
2. Explicit numeric normalization (avoid numeric strings in canonical payload where possible).
3. Stable identifiers for VIP entries and clusters where available.
4. Clear source/scope annotations for aggregated metrics.
5. Omit sections/fields when not computable instead of emitting misleading defaults.

## Non-Goals (This Spec)
1. Frontend rendering behavior details (`dk_dashboard` specific).
2. Schema-breaking redesign details (handled in explicit versioned contract docs).
3. End-user visual styling concerns from Google Sheets (color/gradient implementation specifics).

## Success Criteria
1. Every major sheet operating panel maps to one or more explicit `dk_results` features above.
2. Each feature has defined inputs, computation intent, outputs, and unavailable semantics.
3. Snapshot publishing and operational workflows are specified as first-class product surfaces.
4. Future parity/superset planning can reference this doc as source-of-truth feature inventory.
