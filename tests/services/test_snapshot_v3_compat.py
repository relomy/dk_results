"""Backward compatibility of the exported snapshot schema: previous vs current."""

from __future__ import annotations

from typing import Any

import pytest

from dk_results.services.snapshot_v3.compat import BreakingChange, BreakingKind, breaking_changes


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
        _obj({"rank": INT}, ("rank",)),
        _obj({"rank": INT}),
        [("rank", BreakingKind.BECAME_OPTIONAL)],
        id="required-became-optional",
    ),
    pytest.param(
        _envelope(_obj({"rank": INT, "pmr": INT}, ("rank", "pmr"))),
        _envelope(_obj({"rank": INT, "pmr": INT}, ("rank",))),
        [("sports.*.contests[].vip_lineups[].pmr", BreakingKind.BECAME_OPTIONAL)],
        id="required-became-optional-behind-refs-maps-and-arrays",
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
    pytest.param(
        _obj({"selection_reason": {}}),
        _obj({"selection_reason": {"type": "string", "minLength": 1, "pattern": "^[a-z]+$"}}),
        id="untyped-value-given-a-type-with-limits",
    ),
    pytest.param(
        _envelope(LOOSE),
        _envelope(_obj({"rank": {"type": "integer", "minimum": 1}}, ("rank",))),
        id="loose-section-tightened-to-typed-fields-with-limits",
    ),
]


@pytest.mark.parametrize(("previous", "current"), ADDITIVE_CASES)
def test_additive_change_is_not_breaking(previous: dict[str, Any], current: dict[str, Any]) -> None:
    assert breaking_changes(previous, current) == []


def _limited(keyword: str, limit: Any) -> dict[str, Any]:
    """A field of the type ``keyword`` applies to, carrying that limit (no limit when ``limit`` is None)."""
    base: dict[str, Any] = {
        "minimum": INT,
        "exclusiveMinimum": INT,
        "maximum": INT,
        "exclusiveMaximum": INT,
        "minLength": STR,
        "maxLength": STR,
        "pattern": STR,
        "minItems": {"type": "array", "items": INT},
        "maxItems": {"type": "array", "items": INT},
        "minProperties": {"type": "object"},
        "maxProperties": {"type": "object"},
    }[keyword]
    return base if limit is None else {**base, keyword: limit}


def _limit_rows(keyword: str, loose: Any, tight: Any) -> list[Any]:
    """Rows for one keyword: ``loose`` -> ``tight`` is narrowing, ``None`` is no limit declared."""
    return [
        pytest.param(keyword, loose, tight, id=f"{keyword}-tightened"),
        pytest.param(keyword, None, tight, id=f"{keyword}-added"),
    ]


LIMIT_NARROWING = [
    *_limit_rows("minimum", 0, 1),
    *_limit_rows("exclusiveMinimum", 0, 1),
    *_limit_rows("minLength", 1, 2),
    *_limit_rows("minItems", 1, 2),
    *_limit_rows("minProperties", 1, 2),
    *_limit_rows("maximum", 10, 9),
    *_limit_rows("exclusiveMaximum", 10, 9),
    *_limit_rows("maxLength", 10, 9),
    *_limit_rows("maxItems", 10, 9),
    *_limit_rows("maxProperties", 10, 9),
    pytest.param("pattern", None, "^[A-Z]+$", id="pattern-added"),
    pytest.param("pattern", "^[a-z]+$", "^[A-Z]+$", id="pattern-changed"),
]


@pytest.mark.parametrize(("keyword", "old", "new"), LIMIT_NARROWING)
def test_tightened_or_added_limit_is_type_narrowed(keyword: str, old: Any, new: Any) -> None:
    previous = _obj({"x": _limited(keyword, old)}, ("x",))
    current = _obj({"x": _limited(keyword, new)}, ("x",))

    assert breaking_changes(previous, current) == [
        BreakingChange("x", BreakingKind.TYPE_NARROWED, f"{keyword}: {'none' if old is None else old} -> {new}")
    ]


LIMIT_LOOSENING = [
    pytest.param("minimum", 1, 0, id="minimum-lowered"),
    pytest.param("exclusiveMinimum", 1, 0, id="exclusiveMinimum-lowered"),
    pytest.param("minLength", 2, 1, id="minLength-lowered"),
    pytest.param("minItems", 2, 1, id="minItems-lowered"),
    pytest.param("minProperties", 2, 1, id="minProperties-lowered"),
    pytest.param("maximum", 9, 10, id="maximum-raised"),
    pytest.param("exclusiveMaximum", 9, 10, id="exclusiveMaximum-raised"),
    pytest.param("maxLength", 9, 10, id="maxLength-raised"),
    pytest.param("maxItems", 9, 10, id="maxItems-raised"),
    pytest.param("maxProperties", 9, 10, id="maxProperties-raised"),
    pytest.param("minimum", 1, None, id="minimum-removed"),
    pytest.param("maxLength", 9, None, id="maxLength-removed"),
    pytest.param("pattern", "^[a-z]+$", None, id="pattern-removed"),
    pytest.param("pattern", "^[a-z]+$", "^[a-z]+$", id="pattern-unchanged"),
    pytest.param("minimum", 1, 1, id="minimum-unchanged"),
]


@pytest.mark.parametrize(("keyword", "old", "new"), LIMIT_LOOSENING)
def test_loosened_or_removed_limit_is_not_breaking(keyword: str, old: Any, new: Any) -> None:
    previous = _obj({"x": _limited(keyword, old)}, ("x",))
    current = _obj({"x": _limited(keyword, new)}, ("x",))

    assert breaking_changes(previous, current) == []


def test_limit_raised_on_the_integer_variant_of_a_nullable_field_is_narrowed() -> None:
    previous = _obj({"x": {"anyOf": [{"type": "integer", "minimum": 0}, {"type": "null"}]}}, ("x",))
    current = _obj({"x": {"anyOf": [{"type": "integer", "minimum": 1}, {"type": "null"}]}}, ("x",))

    assert breaking_changes(previous, current) == [BreakingChange("x", BreakingKind.TYPE_NARROWED, "minimum: 0 -> 1")]


def test_limit_raised_on_a_type_list_variant_is_narrowed() -> None:
    previous = _obj({"x": {"type": ["integer", "null"], "minimum": 0}}, ("x",))
    current = _obj({"x": {"type": ["integer", "null"], "minimum": 1}}, ("x",))

    assert breaking_changes(previous, current) == [BreakingChange("x", BreakingKind.TYPE_NARROWED, "minimum: 0 -> 1")]


def test_limit_tightened_behind_refs_maps_and_arrays_is_reported_at_the_field_path() -> None:
    previous = _envelope(_obj({"rank": {"type": "integer", "minimum": 1}}, ("rank",)))
    current = _envelope(_obj({"rank": {"type": "integer", "minimum": 2}}, ("rank",)))

    assert [(c.path, c.kind) for c in breaking_changes(previous, current)] == [
        ("sports.*.contests[].vip_lineups[].rank", BreakingKind.TYPE_NARROWED)
    ]


def test_limit_added_to_a_declared_type_variant_is_narrowed() -> None:
    previous = _obj({"x": {"anyOf": [{"type": "integer"}, {"type": "null"}]}}, ("x",))
    current = _obj({"x": {"anyOf": [{"type": "integer", "minimum": 0}, {"type": "null"}]}}, ("x",))

    assert [c.detail for c in breaking_changes(previous, current)] == ["minimum: none -> 0"]


def test_limit_kept_loose_on_one_of_several_current_variants_is_not_narrowing() -> None:
    previous = _obj({"x": {"anyOf": [{"type": "integer", "minimum": 0}, {"type": "null"}]}}, ("x",))
    current = _obj({"x": {"anyOf": [{"type": "integer", "minimum": 0}, {"type": "integer"}, {"type": "null"}]}}, ("x",))

    assert breaking_changes(previous, current) == []


def test_pattern_still_accepted_by_one_of_several_current_variants_is_not_narrowing() -> None:
    previous = _obj({"x": {"type": "string", "pattern": "^a$"}}, ("x",))
    current = _obj(
        {"x": {"anyOf": [{"type": "string", "pattern": "^a$"}, {"type": "string", "pattern": "^b$"}]}}, ("x",)
    )

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


def _kind(value: str, **fields: Any) -> dict[str, Any]:
    """An object union branch discriminated by a ``kind`` const."""
    return _obj({"kind": {"type": "string", "const": value}, **fields}, ("kind",))


def _union(*branches: dict[str, Any]) -> dict[str, Any]:
    return _obj({"v": {"anyOf": list(branches)}}, ("v",))


BRANCH_A = _kind("a", x=INT)
BRANCH_B = _kind("b", y=INT)

BRANCH_CASES = [
    pytest.param(
        _union(BRANCH_A, BRANCH_B),
        _union(BRANCH_A, _kind("b")),
        [BreakingChange("v.y", BreakingKind.FIELD_REMOVED)],
        id="field-removed-in-a-later-branch",
    ),
    pytest.param(
        _union(BRANCH_A, BRANCH_B),
        _union(BRANCH_A, _kind("b", y=STR)),
        [BreakingChange("v.y", BreakingKind.TYPE_CHANGED, "integer -> string")],
        id="type-changed-in-a-later-branch",
    ),
    pytest.param(
        _union(BRANCH_A, BRANCH_B),
        _union(BRANCH_A),
        [BreakingChange("v", BreakingKind.BRANCH_REMOVED, 'object branch kind="b" has no counterpart')],
        id="discriminated-branch-without-counterpart",
    ),
    pytest.param(
        _union(BRANCH_A, BRANCH_B),
        _union(BRANCH_A, _kind("c", y=INT)),
        [BreakingChange("v", BreakingKind.BRANCH_REMOVED, 'object branch kind="b" has no counterpart')],
        id="discriminator-value-changed",
    ),
    pytest.param(
        _union(_obj({"x": INT}), _obj({"y": INT})),
        _union(_obj({"x": INT}), _obj({})),
        [BreakingChange("v.y", BreakingKind.FIELD_REMOVED)],
        id="positional-fallback-compares-the-second-branch",
    ),
    pytest.param(
        _union(_obj({"x": INT}), _obj({"y": INT})),
        _union(_obj({"x": INT})),
        [BreakingChange("v", BreakingKind.BRANCH_REMOVED, "object branch #2 has no counterpart")],
        id="positional-branch-without-counterpart",
    ),
    pytest.param(
        _union({"type": "array", "items": INT}, {"type": "array", "items": STR}),
        _union({"type": "array", "items": INT}, {"type": "array", "items": INT}),
        [BreakingChange("v[]", BreakingKind.TYPE_CHANGED, "string -> integer")],
        id="array-branches-paired-by-position",
    ),
    pytest.param(
        _union({"type": "array", "items": INT}, {"type": "array", "items": STR}),
        _union({"type": "array", "items": INT}),
        [BreakingChange("v", BreakingKind.BRANCH_REMOVED, "array branch #2 has no counterpart")],
        id="array-branch-without-counterpart",
    ),
    pytest.param(
        _union({"type": "array", "items": BRANCH_A}, {"type": "array", "items": BRANCH_B}),
        _union({"type": "array", "items": BRANCH_B}),
        [BreakingChange("v", BreakingKind.BRANCH_REMOVED, 'array branch kind="a" has no counterpart')],
        id="array-branch-paired-by-item-discriminator",
    ),
]


@pytest.mark.parametrize(("previous", "current", "expected"), BRANCH_CASES)
def test_every_union_branch_is_compared(
    previous: dict[str, Any], current: dict[str, Any], expected: list[BreakingChange]
) -> None:
    assert breaking_changes(previous, current) == expected


BRANCH_COMPATIBLE_CASES = [
    pytest.param(_union(BRANCH_A, BRANCH_B), _union(BRANCH_B, BRANCH_A), id="discriminated-branches-reordered"),
    pytest.param(
        _union(BRANCH_A, BRANCH_B, {"type": "null"}),
        _union({"type": "null"}, BRANCH_B, BRANCH_A),
        id="discriminated-branches-reordered-around-null",
    ),
    pytest.param(
        _union(BRANCH_A, BRANCH_B),
        _union(BRANCH_A, BRANCH_B, _kind("c", z=INT)),
        id="branch-added",
    ),
    pytest.param(
        _union(BRANCH_A, _obj({"y": INT})),
        _union(_obj({"y": INT, "z": INT}), BRANCH_A),
        id="plain-branch-pairs-with-the-remaining-branch-after-discriminated-ones",
    ),
    pytest.param(
        _union({"type": "array", "items": BRANCH_A}, {"type": "array", "items": BRANCH_B}),
        _union({"type": "array", "items": BRANCH_B}, {"type": "array", "items": BRANCH_A}),
        id="array-branches-reordered",
    ),
]


@pytest.mark.parametrize(("previous", "current"), BRANCH_COMPATIBLE_CASES)
def test_reordered_or_added_branches_are_not_breaking(previous: dict[str, Any], current: dict[str, Any]) -> None:
    assert breaking_changes(previous, current) == []


def test_branches_resolved_through_refs_are_paired_by_discriminator() -> None:
    def refs(*names: str) -> dict[str, Any]:
        return _obj(
            {"v": {"anyOf": [{"$ref": f"#/$defs/{name}"} for name in names]}},
            ("v",),
            **{"$defs": {"A": BRANCH_A, "B": BRANCH_B}},
        )

    assert breaking_changes(refs("A", "B"), refs("B", "A")) == []
