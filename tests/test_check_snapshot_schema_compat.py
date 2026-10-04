"""The schema compatibility gate CLI: base schema vs the PR's committed schema."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from dk_results.cli.check_snapshot_schema_compat import main
from dk_results.paths import repo_file


def _schema(**properties: Any) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": sorted(properties), "additionalProperties": False}


def _write(path: Path, content: dict[str, Any] | str) -> Path:
    path.write_text(content if isinstance(content, str) else json.dumps(content), encoding="utf-8")
    return path


def test_passes_with_a_message_when_the_base_has_no_schema_yet(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    current = _write(tmp_path / "current.json", _schema(rank={"type": "integer"}))

    exit_code = main(["--base", str(tmp_path / "missing.json"), "--current", str(current)])

    assert exit_code == 0
    assert "no snapshot schema on the base branch" in capsys.readouterr().out


def test_fails_and_prints_each_breaking_change(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    base = _write(tmp_path / "base.json", _schema(rank={"type": "string"}, pts={"type": "number"}))
    current = _write(tmp_path / "current.json", _schema(rank={"type": "integer"}))

    exit_code = main(["--base", str(base), "--current", str(current)])

    out = capsys.readouterr().out
    assert exit_code == 1
    assert "field_removed: pts" in out
    assert "type_changed: rank (string -> integer)" in out
    assert "breaking-change" in out


def test_passes_an_additive_change(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    base = _write(tmp_path / "base.json", _schema(rank={"type": "integer"}))
    current = _write(tmp_path / "current.json", {**_schema(rank={"type": "integer"}), "required": []})

    assert main(["--base", str(base), "--current", str(current)]) == 0
    assert "no breaking changes" in capsys.readouterr().out


DOC_WITHOUT_ENTRY = "# Snapshot schema 3\n\n## Breaking changes\n\n- 2026-10-01 (#100): `old` field_removed.\n"
DOC_WITH_ENTRY = (
    DOC_WITHOUT_ENTRY + "- 2026-10-06 (#190): `rank` type_changed string -> integer. Migration: parse as int.\n"
)


def _labeled_breaking_run(tmp_path: Path, base_doc: str, doc: str) -> int:
    base = _write(tmp_path / "base.json", _schema(rank={"type": "string"}))
    current = _write(tmp_path / "current.json", _schema(rank={"type": "integer"}))
    return main(
        [
            "--base", str(base),
            "--current", str(current),
            "--breaking-change-label",
            "--base-doc", str(_write(tmp_path / "base.md", base_doc)),
            "--doc", str(_write(tmp_path / "doc.md", doc)),
        ]
    )  # fmt: skip


def test_labeled_breaking_change_fails_until_the_log_gains_an_entry(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = _labeled_breaking_run(tmp_path, DOC_WITHOUT_ENTRY, DOC_WITHOUT_ENTRY)

    out = capsys.readouterr().out
    assert exit_code == 1
    assert "type_changed: rank" in out
    assert "Breaking changes log" in out


def test_labeled_breaking_change_passes_when_the_log_gained_an_entry(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = _labeled_breaking_run(tmp_path, DOC_WITHOUT_ENTRY, DOC_WITH_ENTRY)

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "type_changed: rank" in out
    assert "2026-10-06 (#190)" in out


def test_labeled_breaking_change_counts_a_first_entry_when_the_base_doc_is_missing(tmp_path: Path) -> None:
    base = _write(tmp_path / "base.json", _schema(rank={"type": "string"}))
    current = _write(tmp_path / "current.json", _schema(rank={"type": "integer"}))
    doc = _write(tmp_path / "doc.md", DOC_WITHOUT_ENTRY)

    argv = ["--base", str(base), "--current", str(current), "--breaking-change-label"]
    assert main([*argv, "--base-doc", str(tmp_path / "missing.md"), "--doc", str(doc)]) == 0


COMMITTED_SCHEMA = repo_file("contract", "snapshot.schema.json")


def test_the_committed_schema_passes_against_itself_by_default() -> None:
    assert main(["--base", str(COMMITTED_SCHEMA)]) == 0


def test_tightening_a_loose_section_passes_but_dropping_a_null_does_not(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    schema = json.loads(COMMITTED_SCHEMA.read_text())
    tightened = copy.deepcopy(schema)
    tightened["$defs"]["VipLineupRow"] = {
        **_schema(rank={"type": "integer"}, points={"type": "number"}),
        "title": "VipLineupRow",
    }
    tightened["$defs"]["Contest"]["properties"]["max_entries_per_user"] = {"type": "integer"}

    exit_code = main(["--base", str(COMMITTED_SCHEMA), "--current", str(_write(tmp_path / "c.json", tightened))])

    out = capsys.readouterr().out
    assert exit_code == 1
    assert "1 breaking change(s)" in out
    assert "type_narrowed: sports.*.contests[].max_entries_per_user (integer | null -> integer)" in out
