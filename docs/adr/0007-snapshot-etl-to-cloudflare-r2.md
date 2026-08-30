# Snapshot feed: publish the dashboard snapshot to Cloudflare R2

The dashboard reads its data from a Cloudflare R2 bucket (`dk-dashboard-data`).
Getting a snapshot up there was a hand-run three-step recipe in one operator's
shell history (`export_fixture … && export_fixture publish && npx wrangler r2
object put …`), and that recipe uploaded keys in an order that could briefly
point the dashboard at a snapshot object that did not exist yet.

We add a committed, scheduled **snapshot feed** in `dk_results` that runs
**build → publish → load** each cycle: build one multi-sport snapshot artifact,
derive the latest pointer and day manifest, and load `snapshots/*`,
`manifest/*`, and `latest.json` into the object store the dashboard already
reads. It runs on the existing Raspberry Pi scheduler, keeps no local state,
and orders uploads so the latest pointer is always valid.

## The `feed` module owns only the load step and orchestration

The build step (`db_main.build_live_snapshot`, which selects each sport's live
contest through the DB-driven `SportProcessor` and shapes the schema-3 envelope
via `build_snapshot_v3_envelope`) and the publish step
(`commands.export_fixture.run_publish_snapshot`, which derives `latest.json` and
appends the UTC-day manifest) already exist and are already tested. The feed
**reuses** both. The new code is the **object-store port** and boto3 adapter,
the **load step** (uploading the staged keys), and the end-to-end
orchestration in `feed.pipeline.run_feed` plus the `snapshot_feed.py` entry
point. There is no second implementation of snapshot shaping to keep in sync.

## boto3 over wrangler

The default object-store adapter uses `boto3` against R2's S3-compatible
endpoint rather than shelling out to `wrangler`. The Pi already runs Python;
adding a Node/`wrangler` toolchain there is a heavier footprint, and headless
auth needs a scoped token either way. `boto3` keeps the producer Python-only.

## Ordering and immutability keep the pointer valid

Snapshot keys are immutable and timestamped (`snapshots/live-<snapshot_at>.json`,
`:` rewritten to `-`). Each cycle uploads in the order
`snapshots/<name>.json` → `manifest/<date>.json` → `latest.json` **last**, so
`latest.json` never names an object that is not already present. A failed upload
raises before `latest.json` is touched, leaving the previous pointer intact — a
partial run never advances the dashboard to a broken state.

## Stateless producer; the object store is the source of truth

The feed stages into an ephemeral data root (`mktemp`) and keeps no snapshot
state on the Pi, so a reflashed SD card recovers from the object store alone.
The day manifest is **read from the object store, appended, and written back**
each cycle: `run_feed` seeds the staged manifest with `store.get_json`, lets the
reused publish step append the new entry, then loads the result back with
`store.put_json`.

## Configuration and retention

The bucket name comes from `R2_BUCKET` so renaming it in the dashboard needs no
code change here; credentials and endpoint come from `R2_ACCOUNT_ID`,
`R2_ACCESS_KEY_ID`, and `R2_SECRET_ACCESS_KEY`. No secret is committed. Old
snapshots age out via a **30-day object-store lifecycle rule** on `snapshots/`
and `manifest/` — a bucket-side setting, provisioned out of band, not code. The
lifecycle window is what keeps deep links to older snapshots resolving.

## Testing

The feed pipeline is exercised against a **fake in-memory object store**: given
an injected snapshot artifact and a pre-seeded day manifest, a run leaves the
store with the expected keys, an appended manifest, a latest pointer to the new
snapshot, and snapshot-before-latest ordering. The boto3 adapter's
key/content-type mapping is tested in isolation with an injected fake client.
Real `boto3`/R2 credentials are never touched, so CI stays hermetic and fast.

## Out of scope

The dashboard's reader code is unchanged — it already serves from the object
store (see `dk_dashboard` ADR-0001, which records the read contract). The
scheduler itself stays external. Provisioning the R2 lifecycle rule and the
scoped token are human infra steps handled out of band. Snapshot schema v3 and
the publish file formats are unchanged.
