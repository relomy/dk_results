---
status: accepted
---

# Snapshot ETL: publish the dashboard feed to Cloudflare R2 from the producer

## Context

`dk_results` already builds a multi-sport **snapshot artifact** (`db_main.py
--snapshot-out` → `build_snapshot_v3_envelope`) and derives the dashboard's
`latest.json` + per-UTC-day `manifest` from it (`export_fixture.py publish`).
The `dk_dashboard` Pages Functions already serve those keys out of the R2
bucket `dk-dashboard-data`. The missing stage was **load**: getting the
published keys into that bucket. Until now it existed only as an ad-hoc shell
recipe (`npx wrangler r2 object put`) in one operator's history.

## Decision

Add a scheduled **snapshot feed** owned by `dk_results` that runs
build → publish → load each cycle:

- **Scope**: one multi-sport snapshot artifact per cycle covering every active
  sport that has contests, via the existing DB-driven `db_main --snapshot-out`
  path (not the single-contest `export_fixture` path). Per-sport `status`/`error`
  fields let one sport degrade without aborting the run.
- **Load transport**: `boto3` against R2's S3-compatible endpoint, from inside
  `dk_results`. Rejected: `wrangler` in `dk_dashboard`. The scheduler runs on a
  resource-constrained, headless Raspberry Pi where `dk_results` (Python/`uv`)
  already runs; adding Node + a `dk_dashboard` checkout + `node_modules` there
  is too heavy, and `wrangler`'s stored-login advantage does not exist headless
  (a scoped token is required either way).
- **Stateless producer**: the object store is the source of truth. Each cycle
  stages into an ephemeral **data root** (`mktemp`), reads the current **day
  manifest** from the store, appends the new entry, and re-uploads. Nothing
  snapshot-related persists on the Pi, so a reflashed SD card rebuilds
  correctly.
- **Consistency**: snapshot keys are immutable and timestamped. Upload order is
  `snapshots/<ts>.json` → `manifest/<utc-date>.json` → `latest.json` **last**,
  so the latest pointer never names a key that is not yet stored (the dashboard
  client's retry budget is thin — one immediate retry plus one backed-off
  react-query retry).
- **Retention**: a single R2 lifecycle rule expiring `snapshots/` and
  `manifest/` at **30 days**. The browse timeline needs only today + yesterday;
  the surplus keeps deep-linked snapshot URLs alive, and storage is trivial
  (tens of KB per snapshot).
- **Coupling**: the bucket name is read from an env var (`R2_BUCKET`), never
  hard-coded, so a rename in `dk_dashboard` does not silently break the producer.

## Consequences

- `dk_results` now holds R2 credentials (a scoped write token) in the Pi's
  environment.
- The object store key layout (`snapshots/*`, `manifest/*`, `latest.json`) is a
  contract shared with `dk_dashboard`; see that repo's ADR-0001. Changing it
  requires coordinating both repos.
