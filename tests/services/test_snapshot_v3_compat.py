"""Backward compatibility of the exported snapshot schema: previous vs current."""

from __future__ import annotations

from typing import Any

import pytest

from dk_results.services.snapshot_v3.compat import BreakingKind, breaking_change_log_entries, breaking_changes


def _obj(properties: dict[str, Any], required: tuple[str, ...] = (), **extra: Any) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": list(required),
        "additionalProperties": False,
        **extra,
    }


INT = {"type": "integer"}
STR = {"type": "string"}


def _envelope(vip_row: dict[str, Any]) -> dict[str, Any]:
    """A pydantic-shaped schema: sports map -> contests array -> vip rows, via $ref/$defs."""
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$defs": {
            "Sport": _obj({"contests": {"type": "array", "items": {"$ref": "#/$defs/Contest"}}}, ("contests",)),
            "Contest": _obj({"vip_lineups": {"type": "array", "items": {"$ref": "#/$defs/VipRow"}}}, ("vip_lineups",)),
            "VipRow": vip_row,
        },
        **_obj({"sports": {"type": "object", "additionalProperties": {"$ref": "#/$defs/Sport"}}}, ("sports",)),
    }


BREAKING_CASES = [
    pytest.param(
        _obj({"rank": INT, "points": INT}, ("rank",)),
        _obj({"rank": INT}, ("rank",)),
        [("points", BreakingKind.FIELD_REMOVED)],
        id="field-removed",
    ),
    pytest.param(
        _obj({"rank": INT, "pts": INT}, ("rank",)),
        _obj({"rank": INT, "points": INT}, ("rank",)),
        [("pts", BreakingKind.FIELD_REMOVED)],
        id="field-renamed-is-removed-plus-added",
    ),
    pytest.param(
        _envelope(_obj({"rank": INT, "pmr": INT}, ("rank",))),
        _envelope(_obj({"rank": INT}, ("rank",))),
        [("sports.*.contests[].vip_lineups[].pmr", BreakingKind.FIELD_REMOVED)],
        id="field-removed-behind-refs-maps-and-arrays",
    ),
    pytest.param(
        _obj(
            {"live": {"anyOf": [{"$ref": "#/$defs/Live"}, {"type": "null"}]}},
            ("live",),
            **{"$defs": {"Live": _obj({"cutoff": INT})}},
        ),
        _obj(
            {"live": {"anyOf": [{"$ref": "#/$defs/Live"}, {"type": "null"}]}},
            ("live",),
            **{"$defs": {"Live": _obj({})}},
        ),
        [("live.cutoff", BreakingKind.FIELD_REMOVED)],
        id="field-removed-inside-nullable-ref-union",
    ),
    pytest.param(
        _obj({"rank": INT, "pmr": INT}, ("rank",)),
        _obj({"rank": INT, "pmr": INT}, ("rank", "pmr")),
        [("pmr", BreakingKind.BECAME_REQUIRED)],
        id="optional-became-required",
    ),
    pytest.param(
        _obj({"rank": STR}, ("rank",)),
        _obj({"rank": INT}, ("rank",)),
        [("rank", BreakingKind.TYPE_CHANGED)],
        id="type-changed",
    ),
    pytest.param(
        _obj({"cap": {"anyOf": [INT, {"type": "null"}]}}, ("cap",)),
        _obj({"cap": INT}, ("cap",)),
        [("cap", BreakingKind.TYPE_NARROWED)],
        id="type-narrowed-nullable-to-non-null",
    ),
    pytest.param(
        _obj({"status": {"type": "string", "enum": ["ok", "stale", "error"]}}, ("status",)),
        _obj({"status": {"type": "string", "enum": ["ok", "error"]}}, ("status",)),
        [("status", BreakingKind.ENUM_VALUE_REMOVED)],
        id="enum-value-removed",
    ),
    pytest.param(
        _obj({"schema_version": {"type": "integer", "const": 3}}, ("schema_version",)),
        _obj({"schema_version": {"type": "integer", "const": 4}}, ("schema_version",)),
        [("schema_version", BreakingKind.ENUM_VALUE_REMOVED)],
        id="const-value-changed",
    ),
    pytest.param(
        _obj({"state": STR}, ("state",)),
        _obj({"state": {"type": "string", "enum": ["live", "final"]}}, ("state",)),
        [("state", BreakingKind.TYPE_NARROWED)],
        id="type-narrowed-free-string-to-enum",
    ),
]


@pytest.mark.parametrize(("previous", "current", "expected"), BREAKING_CASES)
def test_breaking_change_is_reported_with_path_and_kind(
    previous: dict[str, Any], current: dict[str, Any], expected: list[tuple[str, BreakingKind]]
) -> None:
    assert [(change.path, change.kind) for change in breaking_changes(previous, current)] == expected


LOOSE = {"type": "object", "properties": {}, "additionalProperties": True}

ADDITIVE_CASES = [
    pytest.param(
        _obj({"rank": INT}, ("rank",)),
        _obj({"rank": INT, "points": {"type": "number"}}, ("rank",)),
        id="optional-field-added",
    ),
    pytest.param(
        _obj({"rank": INT}, ("rank",)),
        _obj({"rank": INT, "points": {"type": "number"}}, ("rank", "points")),
        id="required-field-added",
    ),
    pytest.param(
        _obj({"rank": INT}, ("rank",)),
        _obj({"rank": INT}),
        id="required-field-became-optional",
    ),
    pytest.param(
        _obj({"status": {"type": "string", "enum": ["ok", "error"]}}, ("status",)),
        _obj({"status": {"type": "string", "enum": ["ok", "stale", "error"]}}, ("status",)),
        id="enum-value-added",
    ),
    pytest.param(
        _obj({"rank": {"type": "integer", "title": "Rank"}}, ("rank",)),
        _obj({"rank": {"type": "integer", "title": "Finishing rank", "description": "1-based."}}, ("rank",)),
        id="title-and-description-changed",
    ),
    pytest.param(
        _envelope(LOOSE),
        _envelope(_obj({"rank": INT, "pmr": {"type": "number"}}, ("rank", "pmr"))),
        id="loose-section-tightened-to-typed-fields",
    ),
    pytest.param(
        _obj({"selection_reason": {}}),
        _obj({"selection_reason": STR}),
        id="untyped-value-given-a-type",
    ),
]


@pytest.mark.parametrize(("previous", "current"), ADDITIVE_CASES)
def test_additive_change_is_not_breaking(previous: dict[str, Any], current: dict[str, Any]) -> None:
    assert breaking_changes(previous, current) == []


def test_breaking_change_names_the_previous_and_current_types() -> None:
    [change] = breaking_changes(_obj({"rank": STR}, ("rank",)), _obj({"rank": INT}, ("rank",)))

    assert change.detail == "string -> integer"


def test_recursive_definitions_are_compared_without_looping() -> None:
    node = _obj(
        {
            "name": STR,
            "parent": {"anyOf": [{"$ref": "#/$defs/Node"}, {"type": "null"}]},
            "children": {"type": "array", "items": {"$ref": "#/$defs/Node"}},
        },
        ("name",),
    )
    previous = {"$defs": {"Node": node}, "$ref": "#/$defs/Node"}
    current = {"$defs": {"Node": {**node, "required": ["name", "children"]}}, "$ref": "#/$defs/Node"}

    assert [(c.path, c.kind) for c in breaking_changes(previous, current)] == [
        ("children", BreakingKind.BECAME_REQUIRED)
    ]


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
