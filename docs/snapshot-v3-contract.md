# Snapshot Schema v3 Contract

This document defines the canonical snapshot envelope used by `dk_dashboard` fixtures and runtime consumers.

## Top-Level Envelope

Required fields:

- `schema_version`: must be `3`
- `snapshot_at`: RFC3339 UTC timestamp
- `generated_at`: RFC3339 UTC timestamp
- `sports`: object keyed by normalized sport slug (for example `nba`, `golf`)

## Sport Payload

Each `sports.<sport>` payload is single-contest:

- `status`
- `updated_at`
- `players`
- `primary_contest`
- `contests` with exactly one contest object

## Contest Payload

Required canonical fields:

- `contest_id`
- `contest_key`
- `name`
- `sport`
- `contest_type`
- `start_time`
- `state`
- `entry_fee_cents`
- `prize_pool_cents`
- `currency`
- `max_entries`

Metrics remain additive and deterministic under `contest.metrics`.

## Deterministic Fixture Flow

When live contest data is available, generate with fixed timestamp:

```bash
cd dk_results
UV_CACHE_DIR=$PWD/.uv-cache uv run python export_fixture.py bundle \
  --item NBA:<contest_id> \
  --generated-at 2026-02-26T00:00:00Z \
  --out /tmp/canonical-live-snapshot.v3.json
```

Then publish latest + manifest:

```bash
cd dk_results
UV_CACHE_DIR=$PWD/.uv-cache uv run python export_fixture.py publish \
  --snapshot /tmp/canonical-live-snapshot.v3.json \
  --root /path/to/dk_dashboard/public/mock \
  --snapshot-path snapshots/canonical-live-snapshot.v3.json
```

This keeps `latest.json` and UTC-day manifest entries aligned to the v3 artifact path.
