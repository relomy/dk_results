# Operations

## Runtime model
- `dk_results` is the producer for canonical `schema_version: 3` snapshot artifacts.
- Canonical export flow is the v3 pipeline:
  - `collect -> derive -> build -> validate -> serialize`
- Dashboard-facing artifacts are:
  - snapshot JSON
  - `latest.json`
  - UTC-day manifest entries under `manifest/YYYY-MM-DD.json`

## Canonical export commands

### Bundle export
Generate one canonical v3 snapshot envelope:

```bash
uv run python export_fixture.py bundle \
  --item NBA:188080404 \
  --item GOLF:187937165 \
  --out /tmp/dashboard-data/snapshots/live-2026-02-25T12-00-00Z.json
```

Optional deterministic timestamp for fixtures/repro:

```bash
uv run python export_fixture.py bundle \
  --item NBA:188080404 \
  --out /tmp/dashboard-data/snapshots/canonical-live-snapshot.v3.json \
  --generated-at 2026-02-25T12:00:00Z
```

### Publish helper
Write `latest.json` plus the UTC-day manifest entry from an existing snapshot:

```bash
uv run python export_fixture.py publish \
  --snapshot /tmp/dashboard-data/snapshots/live-2026-02-25T12-00-00Z.json \
  --root /tmp/dashboard-data
```

If the API-visible snapshot path differs from filesystem layout:

```bash
uv run python export_fixture.py publish \
  --snapshot /tmp/output.json \
  --root /tmp/dashboard-data \
  --snapshot-path snapshots/live-2026-02-25T12-00-00Z.json
```

### `db_main` snapshot flow
Produce the canonical v3 envelope from the DB-driven workflow:

```bash
uv run python db_main.py \
  --sport NBA GOLF \
  --snapshot-out /tmp/dashboard-data/snapshots/live-2026-02-25T12-00-00Z.json
```

Then publish `latest.json` + manifest using the same `export_fixture.py publish` helper.

## Output layout
Expected root structure:

```txt
<data-root>/
  latest.json
  manifest/
    YYYY-MM-DD.json
  snapshots/
    <snapshot-file>.json
```

Contract rules:
- `latest.json.latest_snapshot_path` must point to a real file under `snapshots/`
- `latest.json.manifest_today_path` must point to a real file under `manifest/`
- each manifest entry `snapshots[].path` must point to a real file under `snapshots/`

## Cutover checklist
Before promoting a new snapshot build:
1. `uv run pytest -q`
2. `uv run ruff check .`
3. `uv run ty check src/dk_results/services/snapshot_v3 src/dk_results/services/snapshot_exporter.py src/dk_results/commands/export_fixture.py src/dk_results/cli/db_main.py`
4. generate snapshot artifact
5. publish `latest.json` and manifest entry
6. validate the published JSON locally:
   - `latest.json.latest_snapshot_path`
   - `manifest/YYYY-MM-DD.json`
   - referenced snapshot file exists

## Rollback triggers
Rollback immediately if any of these happen after cutover:
- dashboard cannot load `/latest` or `/live/:sport`
- `latest.json` points to a non-existent snapshot
- manifest entry points to a non-existent snapshot
- canonical snapshot fails dashboard contract checks
- exporter verification gate fails on the release branch

## Rollback procedure
Rollback is artifact-based. Do not add runtime compatibility code.

### 1. Repoint `latest.json` + manifest to last known good snapshot
If the prior good snapshot file still exists, republish pointers using that artifact:

```bash
uv run python export_fixture.py publish \
  --snapshot /tmp/dashboard-data/snapshots/<last-known-good>.json \
  --root /tmp/dashboard-data
```

If needed, use `--snapshot-path` so the manifest/latest entry matches the API-visible key.

### 2. If the bad snapshot file was already uploaded remotely
- leave the bad snapshot object in storage if needed for debugging
- only repoint `latest.json` and the current UTC-day manifest entry to the last good artifact

### 3. If code rollback is required
Revert the v3 cutover commits on the release branch, then rerun the full verification gate before the next publish.

## Troubleshooting
- `publish` fails with path error:
  - snapshot file is outside `--root`; provide `--snapshot-path`
- manifest has duplicate entries:
  - republishing the same snapshot path should de-duplicate by `path`; if not, inspect the manifest JSON before upload
- snapshot validation failure:
  - fix producer data or contract violation first; do not patch the dashboard around bad artifacts
