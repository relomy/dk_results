"""The snapshot contract's exported JSON Schema and its committed copy."""

from __future__ import annotations

import json
from pathlib import Path

from dk_results.cli.export_snapshot_schema import main
from dk_results.paths import repo_file

EXPORT_COMMAND = "uv run python export_snapshot_schema.py"
COMMITTED_SCHEMA = repo_file("contract", "snapshot.schema.json")


def _export(tmp_path: Path, name: str = "snapshot.schema.json") -> Path:
    out = tmp_path / name
    assert main(["--out", str(out)]) == 0
    return out


def test_export_writes_the_envelope_contract_as_json_schema(tmp_path: Path) -> None:
    schema = json.loads(_export(tmp_path).read_text())

    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["title"] == "SnapshotEnvelope"
    assert schema["properties"]["schema_version"] == {"const": 3, "title": "Schema Version", "type": "integer"}
    contest = schema["$defs"]["Contest"]
    assert contest["additionalProperties"] is False
    assert {"standings", "vip_lineups", "train_clusters", "max_entries_per_user"} <= set(contest["required"])
    assert not {"ownership_watchlist", "live_metrics", "metrics"} & set(contest["required"])
    assert contest["properties"]["metrics"] == {"$ref": "#/$defs/ContestMetrics"}
    assert contest["properties"]["max_entries_per_user"]["anyOf"] == [{"type": "integer"}, {"type": "null"}]


def test_export_is_byte_for_byte_deterministic(tmp_path: Path) -> None:
    assert _export(tmp_path, "a.json").read_bytes() == _export(tmp_path, "b.json").read_bytes()


def test_committed_schema_is_fresh(tmp_path: Path) -> None:
    exported = _export(tmp_path).read_text()
    committed = COMMITTED_SCHEMA.read_text() if COMMITTED_SCHEMA.is_file() else ""

    assert committed == exported, (
        f"{COMMITTED_SCHEMA.relative_to(repo_file())} is stale; regenerate it with `{EXPORT_COMMAND}` "
        "and commit the result (never edit it by hand)."
    )
