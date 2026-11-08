import json
from argparse import Namespace

import pytest

import dk_results.commands.export_fixture as export_command
from dk_results.services.json_stable import to_stable_json


def _publish(tmp_path, snapshot_at):
    root = tmp_path / "public"
    snapshot_file = root / "snapshots" / "live-1.json"
    snapshot_file.parent.mkdir(parents=True)
    snapshot_file.write_text(
        to_stable_json(
            {
                "schema_version": 3,
                "snapshot_at": snapshot_at,
                "generated_at": "2026-02-15T01:30:05Z",
                "sports": {"nba": {"status": "ok", "updated_at": "2026-02-15T01:30:00Z", "contests": []}},
            }
        ),
        encoding="utf-8",
    )
    args = Namespace(
        snapshot=str(snapshot_file), root=str(root), snapshot_path=None, latest_out=None, manifest_dir=None
    )
    return root, export_command.run_publish_snapshot(args)


@pytest.mark.parametrize(
    "snapshot_at",
    ["2026-02-15T01:30:00Z", "2026-02-15T01:30:00.250Z", "2026-02-15T01:30:00+00:00", "2026-02-15T01:30:00-05:00"],
)
def test_run_publish_snapshot_keeps_each_supported_snapshot_at_form_verbatim(tmp_path, snapshot_at):
    root, rc = _publish(tmp_path, snapshot_at)

    latest = json.loads((root / "latest.json").read_text(encoding="utf-8"))
    assert rc == 0
    assert latest["snapshot_at"] == snapshot_at


@pytest.mark.parametrize("snapshot_at", ["2026-02-15Z", "2026-02-15ZZ", "2026-02-15T01Z:30:00"])
def test_run_publish_snapshot_rejects_malformed_snapshot_at(tmp_path, snapshot_at):
    with pytest.raises(ValueError, match="Invalid isoformat string"):
        _publish(tmp_path, snapshot_at)
