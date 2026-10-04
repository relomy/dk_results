"""The schema compatibility gate CLI: base schema vs the PR's committed schema."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from dk_results.cli.check_snapshot_schema_compat import breaking_change_log_entries, main
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
    current = _write(tmp_path / "current.json", _schema(rank={"type": "integer"}, points={"type": "number"}))

    assert main(["--base", str(base), "--current", str(current)]) == 0
    assert "no breaking changes" in capsys.readouterr().out


SCHEMA_DOC = """# Snapshot schema 3

## Breaking changes

Newest first.

- 2026-10-06 (#190): `sports.*.status` enum_value_removed "stale". Migration: treat a
  missing status as "ok".
- 2026-10-05 (#189): `contest.rank` type_changed string -> integer.

## Rules that apply to every metric

- Omit, never null.
"""


def test_breaking_change_log_entries_are_the_bullets_under_the_log_heading() -> None:
    assert breaking_change_log_entries(SCHEMA_DOC) == [
        '2026-10-06 (#190): `sports.*.status` enum_value_removed "stale". Migration: treat a missing status as "ok".',
        "2026-10-05 (#189): `contest.rank` type_changed string -> integer.",
    ]


def test_a_document_without_the_log_has_no_entries() -> None:
    assert breaking_change_log_entries("# Snapshot schema 3\n\n- Omit, never null.\n") == []


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
    doc = _write(tmp_path / "doc.md", DOC_WITH_ENTRY)

    argv = ["--base", str(base), "--current", str(current), "--breaking-change-label"]
    assert main([*argv, "--base-doc", str(tmp_path / "missing.md"), "--doc", str(doc)]) == 0


COMMITTED_SCHEMA = repo_file("contract", "snapshot.schema.json")


def test_the_committed_schema_passes_against_itself_by_default() -> None:
    assert main(["--base", str(COMMITTED_SCHEMA)]) == 0


def test_on_the_real_schema_tightening_a_loose_section_passes_but_removing_an_enum_value_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Previous: VIP rows still a loose placeholder (as before #182). Current: rows typed, a status dropped."""
    current = json.loads(COMMITTED_SCHEMA.read_text())
    previous = copy.deepcopy(current)
    previous["$defs"]["VipLineupRow"] = {"type": "object", "properties": {}, "additionalProperties": True}
    current["$defs"]["SportPayload"]["properties"]["status"]["enum"].remove("stale")

    exit_code = main(
        ["--base", str(_write(tmp_path / "p.json", previous)), "--current", str(_write(tmp_path / "c.json", current))]
    )

    out = capsys.readouterr().out
    assert exit_code == 1
    assert "1 breaking change(s)" in out
    assert 'enum_value_removed: sports.*.status (removed "stale")' in out


def _doc(*entries: str) -> str:
    return "# Snapshot schema 3\n\n## Breaking changes\n\n" + "".join(f"{entry}\n" for entry in entries)


OLD_ENTRY = "- 2026-10-01 (#100): `pts` field_removed. Migration: read `points`."


@pytest.mark.parametrize(
    ("new_entries", "passes", "unlogged"),
    [
        pytest.param(
            ["- 2026-10-06 (#190): `pts` removed and `rank` is now an integer. Migration: parse as int."],
            True,
            [],
            id="one entry names both paths",
        ),
        pytest.param(
            ["- 2026-10-06 (#190): `pts` field_removed.", "- 2026-10-06 (#190): `rank` type_changed."],
            True,
            [],
            id="one entry per path",
        ),
        pytest.param(
            ["- 2026-10-06 (#190): `pts` field_removed.\n  Also rank type_changed string -> integer."],
            True,
            [],
            id="path named in a wrapped continuation line",
        ),
        pytest.param(
            ["- 2026-10-06 (#190): `rank` type_changed string -> integer."],
            False,
            ["pts"],
            id="a path with no note",
        ),
        pytest.param(
            ["- 2026-10-06 (#190): schema changed, see the PR."],
            False,
            ["pts", "rank"],
            id="an entry naming no path",
        ),
        pytest.param(
            ["- 2026-10-06 (#190): `ranking` type_changed and `pts_total` removed."],
            False,
            ["pts", "rank"],
            id="a longer path does not cover its prefix",
        ),
        pytest.param(
            ["- 2026-10-06 (#190): `contest.pts` and `contest.rank` changed."],
            False,
            ["pts", "rank"],
            id="a longer dotted path does not cover a shorter one",
        ),
    ],
)
def test_labeled_breaking_changes_pass_only_when_every_path_has_a_new_log_entry(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], new_entries: list[str], passes: bool, unlogged: list[str]
) -> None:
    base = _write(tmp_path / "base.json", _schema(rank={"type": "string"}, pts={"type": "number"}))
    current = _write(tmp_path / "current.json", _schema(rank={"type": "integer"}))
    argv = [
        "--base", str(base),
        "--current", str(current),
        "--breaking-change-label",
        "--base-doc", str(_write(tmp_path / "base.md", _doc(OLD_ENTRY))),
        "--doc", str(_write(tmp_path / "doc.md", _doc(*new_entries, OLD_ENTRY))),
    ]  # fmt: skip

    exit_code = main(argv)

    out = capsys.readouterr().out
    assert exit_code == (0 if passes else 1)
    for path in unlogged:
        assert f"no new Breaking changes log entry names `{path}`" in out
    if passes:
        assert "no new Breaking changes log entry" not in out


def test_an_entry_that_was_already_in_the_base_log_covers_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    base = _write(tmp_path / "base.json", _schema(pts={"type": "number"}, rank={"type": "integer"}))
    current = _write(tmp_path / "current.json", _schema(rank={"type": "integer"}))
    doc = _write(tmp_path / "doc.md", _doc("- 2026-10-06 (#190): `rank` renamed.", OLD_ENTRY))
    base_doc = _write(tmp_path / "base.md", _doc(OLD_ENTRY))

    argv = ["--base", str(base), "--current", str(current), "--breaking-change-label"]
    exit_code = main([*argv, "--base-doc", str(base_doc), "--doc", str(doc)])

    assert exit_code == 1
    assert "no new Breaking changes log entry names `pts`" in capsys.readouterr().out
