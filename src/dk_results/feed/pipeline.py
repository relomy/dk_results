"""Feed orchestration and the load step.

``run_feed`` takes an already-built snapshot artifact and an
:class:`~dk_results.feed.object_store.ObjectStore`, reuses the existing publish
step to derive ``latest.json`` and the appended day manifest, then loads the
snapshot, manifest, and latest pointer into the store. The build and publish
steps are reused, not reimplemented; this module owns only the load step and
the end-to-end orchestration.

The producer keeps no local state: it stages into an ephemeral data root, reads
the day manifest from the object store, appends via the publish step, and writes
it back. The object store is the source of truth.
"""

from __future__ import annotations

import contextlib
import json
import logging
import shutil
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from dk_results.commands.export_fixture import run_publish_snapshot
from dk_results.feed.object_store import ObjectStore
from dk_results.services.json_stable import to_stable_json

logger = logging.getLogger(__name__)

LATEST_KEY = "latest.json"


@dataclass(frozen=True)
class FeedResult:
    """Outcome of one feed cycle: the keys loaded, in upload order."""

    snapshot_key: str
    manifest_key: str
    latest_key: str
    uploaded_keys: list[str]


def _require_snapshot_at(snapshot: dict[str, Any]) -> str:
    value = str(snapshot.get("snapshot_at") or "").strip()
    if not value:
        raise ValueError("Snapshot payload missing required field: snapshot_at")
    return value


def _snapshot_name(snapshot_at: str) -> str:
    # Immutable, timestamped key; ':' is unsafe in object keys and filenames.
    stamp = snapshot_at.replace(":", "-")
    return f"live-{stamp}.json"


@contextlib.contextmanager
def _ephemeral_root(data_root: str | Path | None) -> Iterator[Path]:
    if data_root is not None:
        root = Path(data_root)
        root.mkdir(parents=True, exist_ok=True)
        yield root
        return
    tmp = tempfile.mkdtemp(prefix="dk-feed-")
    try:
        yield Path(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _load_json(path: Path) -> dict[str, Any]:
    return dict(json.loads(path.read_text(encoding="utf-8")))


def run_feed(
    snapshot: dict[str, Any],
    store: ObjectStore,
    *,
    data_root: str | Path | None = None,
) -> FeedResult:
    """Publish and load one built snapshot artifact into ``store``.

    Reads today's manifest from ``store``, reuses the publish step to derive the
    appended manifest and ``latest.json``, then uploads
    ``snapshots/<name>.json`` → ``manifest/<date>.json`` → ``latest.json`` in
    that order. If any upload raises, ``latest.json`` is not advanced.
    """

    snapshot_at = _require_snapshot_at(snapshot)
    date_utc = snapshot_at[:10]
    name = _snapshot_name(snapshot_at)
    snapshot_key = f"snapshots/{name}"
    manifest_key = f"manifest/{date_utc}.json"

    with _ephemeral_root(data_root) as root:
        # Stage the built snapshot artifact under the API-visible layout so the
        # publish step resolves its relative path to the object-store key.
        snapshot_path = root / "snapshots" / name
        snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        snapshot_path.write_text(to_stable_json(snapshot), encoding="utf-8")

        # Seed today's manifest from the object store so the reused publish step
        # appends to it rather than starting empty.
        existing_manifest = store.get_json(manifest_key)
        if existing_manifest is not None:
            manifest_dir = root / "manifest"
            manifest_dir.mkdir(parents=True, exist_ok=True)
            (manifest_dir / f"{date_utc}.json").write_text(to_stable_json(existing_manifest), encoding="utf-8")

        # Reuse the publish step: derive latest.json and the appended manifest.
        run_publish_snapshot(
            SimpleNamespace(
                snapshot=str(snapshot_path),
                root=str(root),
                snapshot_path=snapshot_key,
                latest_out=None,
                manifest_dir=None,
            )
        )

        snapshot_body = _load_json(snapshot_path)
        manifest_body = _load_json(root / "manifest" / f"{date_utc}.json")
        latest_body = _load_json(root / "latest.json")

    # Load step. The snapshot and its manifest are immutable and must exist
    # before latest.json names them, so latest.json is uploaded last. A failed
    # upload raises before latest.json is touched, leaving the previous pointer
    # intact.
    uploaded: list[str] = []
    store.put_json(snapshot_key, snapshot_body)
    uploaded.append(snapshot_key)
    store.put_json(manifest_key, manifest_body)
    uploaded.append(manifest_key)
    store.put_json(LATEST_KEY, latest_body)
    uploaded.append(LATEST_KEY)

    logger.info("feed uploaded keys=%s", ",".join(uploaded))
    return FeedResult(
        snapshot_key=snapshot_key,
        manifest_key=manifest_key,
        latest_key=LATEST_KEY,
        uploaded_keys=uploaded,
    )
