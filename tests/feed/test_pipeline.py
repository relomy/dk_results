import json

import pytest

from dk_results.feed.object_store import ObjectStoreError
from dk_results.feed.pipeline import run_feed


class FakeObjectStore:
    """In-memory ObjectStore: asserts external behavior through the seam."""

    def __init__(self) -> None:
        self.objects: dict[str, dict] = {}
        self.put_order: list[str] = []
        self.content_types: dict[str, str] = {}
        self.fail_keys: set[str] = set()

    def get_json(self, key: str) -> dict | None:
        value = self.objects.get(key)
        return dict(value) if value is not None else None

    def put_json(self, key: str, body: dict, content_type: str = "application/json") -> None:
        if key in self.fail_keys:
            raise ObjectStoreError(f"injected failure for {key}")
        self.objects[key] = json.loads(json.dumps(body))
        self.content_types[key] = content_type
        self.put_order.append(key)


def _snapshot(snapshot_at: str = "2026-02-15T01:30:00Z") -> dict:
    return {
        "schema_version": 3,
        "snapshot_at": snapshot_at,
        "generated_at": "2026-02-15T01:30:07Z",
        "sports": {
            "nba": {
                "status": "ok",
                "updated_at": "2026-02-15T01:30:00Z",
                "primary_contest": {"contest_id": "111"},
                "contests": [{"contest_id": "111", "state": "live"}],
                "players": [],
            },
            "golf": {
                "status": "ok",
                "updated_at": "2026-02-15T01:30:00Z",
                "primary_contest": {"contest_id": "222"},
                "contests": [{"contest_id": "222", "state": "upcoming"}],
                "players": [],
            },
        },
    }


SNAPSHOT_KEY = "snapshots/live-2026-02-15T01-30-00Z.json"
MANIFEST_KEY = "manifest/2026-02-15.json"
LATEST_KEY = "latest.json"


def test_run_feed_loads_expected_keys(tmp_path):
    store = FakeObjectStore()

    result = run_feed(_snapshot(), store, data_root=tmp_path)

    assert set(store.objects) == {SNAPSHOT_KEY, MANIFEST_KEY, LATEST_KEY}
    assert result.snapshot_key == SNAPSHOT_KEY
    assert result.manifest_key == MANIFEST_KEY

    latest = store.objects[LATEST_KEY]
    assert latest["latest_snapshot_path"] == SNAPSHOT_KEY
    assert latest["manifest_today_path"] == MANIFEST_KEY
    assert latest["available_sports"] == ["golf", "nba"]

    manifest = store.objects[MANIFEST_KEY]
    paths = [entry["path"] for entry in manifest["snapshots"]]
    assert paths == [SNAPSHOT_KEY]


def test_run_feed_appends_to_existing_day_manifest(tmp_path):
    store = FakeObjectStore()
    store.objects[MANIFEST_KEY] = {
        "manifest_version": 1,
        "date_utc": "2026-02-15",
        "generated_at": "2026-02-15T00:00:00Z",
        "snapshots": [
            {
                "snapshot_at": "2026-02-15T00:00:00Z",
                "path": "snapshots/live-2026-02-15T00-00-00Z.json",
                "byte_size": 10,
                "sports_present": ["nba"],
                "contest_counts_by_sport": {"nba": 1},
                "state_counts": {"live": 1},
                "sports_status": {},
            }
        ],
    }

    run_feed(_snapshot(), store, data_root=tmp_path)

    manifest = store.objects[MANIFEST_KEY]
    paths = [entry["path"] for entry in manifest["snapshots"]]
    assert set(paths) == {SNAPSHOT_KEY, "snapshots/live-2026-02-15T00-00-00Z.json"}
    # Newest first.
    assert paths[0] == SNAPSHOT_KEY


def test_run_feed_uploads_snapshot_and_manifest_before_latest(tmp_path):
    store = FakeObjectStore()

    run_feed(_snapshot(), store, data_root=tmp_path)

    assert store.put_order == [SNAPSHOT_KEY, MANIFEST_KEY, LATEST_KEY]
    assert store.put_order.index(SNAPSHOT_KEY) < store.put_order.index(LATEST_KEY)
    assert store.content_types[SNAPSHOT_KEY] == "application/json"


def test_failed_upload_leaves_previous_latest_pointer_intact(tmp_path):
    store = FakeObjectStore()
    previous_latest = {"latest_snapshot_path": "snapshots/old.json"}
    store.objects[LATEST_KEY] = dict(previous_latest)
    store.fail_keys = {MANIFEST_KEY}

    with pytest.raises(ObjectStoreError):
        run_feed(_snapshot(), store, data_root=tmp_path)

    # The immutable snapshot may be uploaded, but latest.json must not advance.
    assert store.objects[LATEST_KEY] == previous_latest
    assert LATEST_KEY not in store.put_order
