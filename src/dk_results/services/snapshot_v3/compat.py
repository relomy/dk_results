"""Backward-compatibility gate for the exported snapshot JSON Schema.

``breaking_changes(previous, current)`` compares two exported schemas (plain
dicts, no I/O) and returns every change that can break a consumer built
against ``previous``. ``$ref``/``$defs`` are resolved and ``anyOf``/``oneOf``
unions are flattened, so the pydantic export's shape doesn't matter.

The gate guards what ``previous`` declared: a declared field stays, a declared
type keeps accepting what it accepted, a declared optional field stays
optional, a declared enum keeps its values. What ``previous`` left open (a
loose section with no declared fields, a value with no declared type) carries
no promise, so declaring it later is not breaking. Additions never are.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

Schema = Mapping[str, Any]


class BreakingKind(StrEnum):
    """How a change breaks the previous contract. A rename is a removal plus an addition."""

    FIELD_REMOVED = "field_removed"
    BECAME_REQUIRED = "became_required"
    BECAME_OPTIONAL = "became_optional"
    TYPE_CHANGED = "type_changed"
    TYPE_NARROWED = "type_narrowed"
    ENUM_VALUE_REMOVED = "enum_value_removed"


@dataclass(frozen=True, order=True)
class BreakingChange:
    """One breaking change: where (a dotted path; ``*`` is any map key, ``[]`` any item) and how."""

    path: str
    kind: BreakingKind
    detail: str = ""


def breaking_changes(previous: Schema, current: Schema) -> list[BreakingChange]:
    """Every breaking change from ``previous`` to ``current``, sorted by path."""
    comparison = _Comparison(previous, current)
    comparison.compare("", previous, current)
    return sorted(set(comparison.changes))


def _child(path: str, name: str) -> str:
    return f"{path}.{name}" if path else name


def _resolve(root: Schema, node: Schema) -> Schema:
    """Follow ``$ref`` (a local JSON pointer such as ``#/$defs/Contest``)."""
    while "$ref" in node:
        target: Any = root
        for part in str(node["$ref"]).removeprefix("#/").split("/"):
            target = target[part]
        node = target
    return node


def _variants(root: Schema, node: Schema) -> list[Schema]:
    """The alternatives a node accepts, with refs resolved and unions flattened."""
    node = _resolve(root, node)
    union = node.get("anyOf") or node.get("oneOf")
    if not union:
        return [node]
    return [variant for member in union for variant in _variants(root, member)]


_JSON_TYPES: tuple[tuple[type, str], ...] = (
    (bool, "boolean"),
    (int, "integer"),
    (float, "number"),
    (str, "string"),
    (type(None), "null"),
    (list, "array"),
    (dict, "object"),
)


def _json_type(value: Any) -> str:
    return next(name for py_type, name in _JSON_TYPES if isinstance(value, py_type))


def _variant_types(variant: Schema) -> set[str] | None:
    """JSON types one variant accepts; ``None`` when it leaves the type open."""
    declared = variant.get("type")
    if declared is not None:
        return {declared} if isinstance(declared, str) else set(declared)
    if "const" in variant:
        return {_json_type(variant["const"])}
    if "enum" in variant:
        return {_json_type(value) for value in variant["enum"]}
    return None


def _accepted_types(variants: list[Schema]) -> frozenset[str] | None:
    accepted: set[str] = set()
    for variant in variants:
        types = _variant_types(variant)
        if types is None:
            return None
        accepted |= types
    return frozenset(accepted)


Values = dict[str, frozenset[str] | None]


def _variant_values(variant: Schema) -> Values:
    """Per JSON type, the values one variant allows (``None``: any value of that type)."""
    if "const" in variant:
        listed = [variant["const"]]
    elif "enum" in variant:
        listed = list(variant["enum"])
    else:
        return dict.fromkeys(_variant_types(variant) or ())
    values: dict[str, set[str]] = {}
    for value in listed:
        values.setdefault(_json_type(value), set()).add(json.dumps(value, sort_keys=True))
    return {type_name: frozenset(encoded) for type_name, encoded in values.items()}


def _allowed_values(variants: list[Schema]) -> Values:
    allowed: Values = {}
    for variant in variants:
        for type_name, values in _variant_values(variant).items():
            known = allowed.get(type_name, frozenset())
            allowed[type_name] = None if values is None or known is None else known | values
    return allowed


def _value_change(
    path: str, type_name: str, old: frozenset[str] | None, new: frozenset[str] | None
) -> BreakingChange | None:
    if new is None or old == new:
        return None
    if old is None:
        return BreakingChange(path, BreakingKind.TYPE_NARROWED, f"{type_name} -> one of {', '.join(sorted(new))}")
    removed = old - new
    if not removed:
        return None
    return BreakingChange(path, BreakingKind.ENUM_VALUE_REMOVED, f"removed {', '.join(sorted(removed))}")


def _describe(types: frozenset[str] | None) -> str:
    return " | ".join(sorted(types)) if types is not None else "any"


_NUMERIC_LIMITS = ("minimum", "exclusiveMinimum", "maximum", "exclusiveMaximum")
_LOWER_LIMITS = frozenset({"minimum", "exclusiveMinimum", "minLength", "minItems", "minProperties"})
_LIMITS_BY_TYPE: dict[str, tuple[str, ...]] = {
    "integer": _NUMERIC_LIMITS,
    "number": _NUMERIC_LIMITS,
    "string": ("minLength", "maxLength", "pattern"),
    "array": ("minItems", "maxItems"),
    "object": ("minProperties", "maxProperties"),
}


def _limit(variant: Schema, keyword: str) -> Any:
    """The keyword's value, or ``None``; a boolean (draft-4 ``exclusiveMinimum``) is no numeric limit."""
    value = variant.get(keyword)
    return None if isinstance(value, bool) else value


def _loosest(keyword: str, limits: list[Any], old: Any) -> Any:
    """The limit that accepts the most among the current alternatives (``None``: unlimited)."""
    if any(limit is None for limit in limits):
        return None
    if keyword == "pattern":
        return old if old in limits else limits[0]
    return min(limits) if keyword in _LOWER_LIMITS else max(limits)


def _narrows(keyword: str, old: Any, new: Any) -> bool:
    """Whether the current limit can reject a value the previous one accepted.

    A pattern can't be compared by containment (undecidable), so any other pattern counts as narrowing.
    """
    if new is None or new == old:
        return False
    if old is None or keyword == "pattern":
        return True
    return new > old if keyword in _LOWER_LIMITS else new < old


def _first_of_type(variants: list[Schema], type_name: str) -> Schema | None:
    return next((v for v in variants if v.get("type") == type_name), None)


class _Comparison:
    def __init__(self, previous: Schema, current: Schema) -> None:
        self._previous_root = previous
        self._current_root = current
        self.changes: list[BreakingChange] = []
        self._in_progress: set[tuple[int, int]] = set()

    def compare(self, path: str, previous: Schema, current: Schema) -> None:
        old = _variants(self._previous_root, previous)
        new = _variants(self._current_root, current)
        self._compare_types(path, _accepted_types(old), _accepted_types(new))
        if _accepted_types(old) is not None and _accepted_types(old) == _accepted_types(new):
            self._compare_values(path, _allowed_values(old), _allowed_values(new))
        self._compare_limits(path, old, new)
        self._compare_objects(path, _first_of_type(old, "object"), _first_of_type(new, "object"))
        self._compare_arrays(path, _first_of_type(old, "array"), _first_of_type(new, "array"))

    def _compare_types(self, path: str, old: frozenset[str] | None, new: frozenset[str] | None) -> None:
        if old is None or old == new:
            return
        kind = BreakingKind.TYPE_NARROWED if new is not None and new < old else BreakingKind.TYPE_CHANGED
        self.changes.append(BreakingChange(path, kind, f"{_describe(old)} -> {_describe(new)}"))

    def _compare_values(self, path: str, old: Values, new: Values) -> None:
        for type_name, old_values in old.items():
            change = _value_change(path, type_name, old_values, new[type_name])
            if change is not None:
                self.changes.append(change)

    def _compare_limits(self, path: str, old: list[Schema], new: list[Schema]) -> None:
        """Per type the previous schema declared, report a limit the current one tightens or adds."""
        for old_variant in old:
            for type_name in sorted(_variant_types(old_variant) or ()):
                matching = [v for v in new if type_name in (_variant_types(v) or {type_name})]
                for keyword in _LIMITS_BY_TYPE.get(type_name, ()) if matching else ():
                    self._compare_limit(path, keyword, _limit(old_variant, keyword), matching)

    def _compare_limit(self, path: str, keyword: str, old: Any, matching: list[Schema]) -> None:
        new = _loosest(keyword, [_limit(variant, keyword) for variant in matching], old)
        if _narrows(keyword, old, new):
            detail = f"{keyword}: {'none' if old is None else old} -> {new}"
            self.changes.append(BreakingChange(path, BreakingKind.TYPE_NARROWED, detail))

    def _compare_objects(self, path: str, old: Schema | None, new: Schema | None) -> None:
        """Compare two object schemas; a pair already being compared up the stack is a cycle."""
        if old is None or new is None or (id(old), id(new)) in self._in_progress:
            return
        self._in_progress.add((id(old), id(new)))
        self._compare_properties(path, old, new)
        self._in_progress.discard((id(old), id(new)))

    def _compare_properties(self, path: str, old: Schema, new: Schema) -> None:
        new_props = new.get("properties", {})
        old_required, new_required = set(old.get("required", ())), set(new.get("required", ()))
        for name, old_prop in old.get("properties", {}).items():
            if name not in new_props:
                self.changes.append(BreakingChange(_child(path, name), BreakingKind.FIELD_REMOVED))
                continue
            if name in new_required - old_required:
                self.changes.append(BreakingChange(_child(path, name), BreakingKind.BECAME_REQUIRED))
            if name in old_required - new_required:
                self.changes.append(BreakingChange(_child(path, name), BreakingKind.BECAME_OPTIONAL))
            self.compare(_child(path, name), old_prop, new_props[name])
        old_values, new_values = old.get("additionalProperties"), new.get("additionalProperties")
        if isinstance(old_values, Mapping) and isinstance(new_values, Mapping):
            self.compare(_child(path, "*"), old_values, new_values)

    def _compare_arrays(self, path: str, old: Schema | None, new: Schema | None) -> None:
        if old is None or new is None:
            return
        old_items, new_items = old.get("items"), new.get("items")
        if isinstance(old_items, Mapping) and isinstance(new_items, Mapping):
            self.compare(f"{path}[]", old_items, new_items)
