"""Checks for the ``metrics`` section of a snapshot contest.

Distance to cash, non-cashing, VIP ownership summary and threat (top swing players, field
remaining, VIP-versus-field leverage). ``validate.validate_v3_envelope`` runs them.
"""

from __future__ import annotations

from itertools import filterfalse
from typing import Any

from dk_results.services.snapshot_v3.contracts import validate_distance_to_cash_rows, validate_top_swing_players
from dk_results.services.snapshot_v3.models.metrics import (
    FIELD_REMAINING_SCOPE,
    FIELD_REMAINING_SOURCE,
    LEVERAGE_SEMANTICS,
    OWNERSHIP_SUMMARY_SCOPE,
    OWNERSHIP_SUMMARY_SOURCE,
    TOP_REMAINING_PLAYERS_LIMIT,
)
from dk_results.services.snapshot_v3.normalize import is_locked_snapshot_slot, resolve_lineup_slots
from dk_results.services.snapshot_v3.validate_values import _is_finite_number, _is_non_empty_string


def _prefix_contract_path(sport: str, message: str) -> str:
    return message.replace("contest.", f"sports.{sport}.contests[0].")


def _add_player_keys_from_rows(rows: Any, keys: set[str]) -> None:
    if not isinstance(rows, list):
        return
    for row in rows:
        if not isinstance(row, dict):
            continue
        player_key = row.get("player_key")
        if _is_non_empty_string(player_key):
            keys.add(str(player_key))


def _add_player_keys_from_vip_lineups(vip_lineups: Any, keys: set[str]) -> None:
    if not isinstance(vip_lineups, list):
        return
    for vip_row in vip_lineups:
        if not isinstance(vip_row, dict):
            continue
        slots = resolve_lineup_slots(vip_row)
        if slots is None:
            continue
        _add_player_keys_from_rows(list(filterfalse(is_locked_snapshot_slot, slots)), keys)


def _collect_known_player_keys(sport_payload: dict[str, Any], contest: dict[str, Any]) -> set[str]:
    keys: set[str] = set()
    _add_player_keys_from_rows(sport_payload.get("players"), keys)
    _add_player_keys_from_rows(contest.get("players"), keys)
    _add_player_keys_from_vip_lineups(contest.get("vip_lineups"), keys)
    return keys


def _validate_contest_metrics(sport: str, sport_payload: dict[str, Any], contest: dict[str, Any]) -> list[str]:
    metrics = contest.get("metrics")
    if not isinstance(metrics, dict):
        return []
    violations = []
    distance_to_cash = metrics.get("distance_to_cash")
    if isinstance(distance_to_cash, dict) and isinstance(distance_to_cash.get("per_vip"), list):
        violations.extend(
            _prefix_contract_path(sport, message)
            for message in validate_distance_to_cash_rows(distance_to_cash["per_vip"])
        )
    violations.extend(_validate_non_cashing(sport, metrics.get("non_cashing")))
    if "ownership_summary" in metrics:
        violations.extend(_validate_ownership_summary(sport, metrics["ownership_summary"]))
    violations.extend(_validate_threat(sport, sport_payload, contest, metrics.get("threat")))
    return violations


def _validate_threat(sport: str, sport_payload: dict[str, Any], contest: dict[str, Any], threat: Any) -> list[str]:
    if not isinstance(threat, dict):
        return []
    violations: list[str] = []
    if isinstance(threat.get("top_swing_players"), list):
        violations.extend(_validate_top_swing_players(sport, sport_payload, contest, threat["top_swing_players"]))
    violations.extend(_validate_threat_field_metrics(sport, threat))
    return violations


def _validate_non_cashing(sport: str, non_cashing: Any) -> list[str]:
    # A non-dict section is reported by _validate_metrics_section.
    if not isinstance(non_cashing, dict):
        return []
    path = f"sports.{sport}.contests[0].metrics.non_cashing"
    violations: list[str] = []
    users = non_cashing.get("users_not_cashing")
    if "users_not_cashing" not in non_cashing:
        violations.append(f"{path}.users_not_cashing is required")
    elif not isinstance(users, int) or isinstance(users, bool) or users < 0:
        violations.append(f"{path}.users_not_cashing has invalid type")
    if "avg_pmr_remaining" not in non_cashing:
        violations.append(f"{path}.avg_pmr_remaining is required")
    elif not _is_finite_number(non_cashing["avg_pmr_remaining"]):
        violations.append(f"{path}.avg_pmr_remaining has invalid type")
    if "top_remaining_players" in non_cashing:
        violations.extend(_validate_top_remaining_players(path, non_cashing["top_remaining_players"]))
    return violations


def _validate_top_remaining_players(path: str, rows: Any) -> list[str]:
    if not isinstance(rows, list):
        return [f"{path}.top_remaining_players has invalid type"]
    violations: list[str] = []
    if len(rows) > TOP_REMAINING_PLAYERS_LIMIT:
        violations.append(f"{path}.top_remaining_players has more than {TOP_REMAINING_PLAYERS_LIMIT} rows")
    for index, row in enumerate(rows):
        row_path = f"{path}.top_remaining_players[{index}]"
        if not isinstance(row, dict):
            violations.append(f"{row_path} must be an object")
            continue
        if not _is_non_empty_string(row.get("player_name")):
            violations.append(f"{row_path}.player_name is required")
        if not _is_finite_number(row.get("ownership_remaining_pct")):
            violations.append(f"{row_path}.ownership_remaining_pct has invalid type")
    return violations


def _validate_ownership_summary(sport: str, summary: Any) -> list[str]:
    path = f"sports.{sport}.contests[0].metrics.ownership_summary"
    if not isinstance(summary, dict):
        return [f"{path} has invalid type"]
    violations: list[str] = []
    if summary.get("source") != OWNERSHIP_SUMMARY_SOURCE:
        violations.append(f"{path}.source must be {OWNERSHIP_SUMMARY_SOURCE}")
    if summary.get("scope") != OWNERSHIP_SUMMARY_SCOPE:
        violations.append(f"{path}.scope must be {OWNERSHIP_SUMMARY_SCOPE}")
    rows = summary.get("per_vip")
    if not isinstance(rows, list):
        violations.append(f"{path}.per_vip has invalid type")
        return violations
    for index, row in enumerate(rows):
        row_path = f"{path}.per_vip[{index}]"
        if not isinstance(row, dict):
            violations.append(f"{row_path} must be an object")
            continue
        violations.extend(_validate_ownership_summary_row(row_path, row))
    return violations


def _validate_ownership_summary_row(path: str, row: dict[str, Any]) -> list[str]:
    violations: list[str] = []
    if not _is_non_empty_string(row.get("vip_entry_key")):
        violations.append(f"{path}.vip_entry_key is required")
    violations.extend(
        f"{path}.{field} has invalid type"
        for field in ("entry_key", "display_name")
        if field in row and not _is_non_empty_string(row[field])
    )
    violations.extend(_validate_ownership_summary_numbers(path, row))
    violations.extend(_validate_partial_flag(path, row))
    return violations


def _validate_partial_flag(path: str, row: dict[str, Any]) -> list[str]:
    if "is_partial" not in row:
        return [f"{path}.is_partial is required"]
    if not isinstance(row["is_partial"], bool):
        return [f"{path}.is_partial has invalid type"]
    return []


def _validate_ownership_summary_numbers(path: str, row: dict[str, Any]) -> list[str]:
    violations = [f"{path}.total_ownership_pct is required"] if "total_ownership_pct" not in row else []
    violations.extend(
        f"{path}.{field} has invalid type"
        for field in ("total_ownership_pct", "ownership_in_play_pct")
        if field in row and (not _is_finite_number(row[field]) or row[field] < 0)
    )
    return violations


def _validate_top_swing_players(
    sport: str, sport_payload: dict[str, Any], contest: dict[str, Any], rows: list[Any]
) -> list[str]:
    violations = [_prefix_contract_path(sport, message) for message in validate_top_swing_players(rows)]
    known_keys = _collect_known_player_keys(sport_payload, contest)
    seen_keys: set[str] = set()
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or not _is_non_empty_string(row.get("player_key")):
            continue
        key = str(row["player_key"])
        if known_keys and key not in known_keys:
            violations.append(
                f"sports.{sport}.contests[0].metrics.threat.top_swing_players[{index}].player_key "
                "is not in known contest player set"
            )
        if key in seen_keys:
            violations.append(
                f"sports.{sport}.contests[0].metrics.threat.top_swing_players has duplicate player_key {key}"
            )
            break
        seen_keys.add(key)
    return violations


_THREAT_ENUM_FIELDS = {
    "leverage_semantics": LEVERAGE_SEMANTICS,
    "field_remaining_scope": FIELD_REMAINING_SCOPE,
    "field_remaining_source": FIELD_REMAINING_SOURCE,
}


_FIELD_REMAINING_KEYS = (*_THREAT_ENUM_FIELDS, "field_remaining_pct", "field_remaining_is_partial")


_FIELD_REMAINING_TYPE_CHECKS = {
    "field_remaining_pct": _is_finite_number,
    "field_remaining_is_partial": lambda value: isinstance(value, bool),
}


_LEVERAGE_STRING_FIELDS = ("vip_entry_key", "entry_key", "display_name")


_LEVERAGE_NUMBER_FIELDS = ("vip_remaining_pct", "field_remaining_pct", "uniqueness_delta_pct")


def _validate_threat_field_metrics(sport: str, threat: dict[str, Any]) -> list[str]:
    """Check the field-remaining and VIP-leverage parts of ``metrics.threat``."""

    path = f"sports.{sport}.contests[0].metrics.threat"
    violations = _validate_field_remaining_group(path, threat)
    if "vip_vs_field_leverage" in threat:
        if "field_remaining_pct" not in threat:
            violations.append(f"{path}.vip_vs_field_leverage requires field_remaining_pct")
        violations.extend(_validate_vip_vs_field_leverage(path, threat["vip_vs_field_leverage"]))
    return violations


def _missing_field_remaining_keys(path: str, threat: dict[str, Any]) -> list[str]:
    if not any(key in threat for key in _FIELD_REMAINING_KEYS):
        return []
    return [f"{path}.{key} is required" for key in _FIELD_REMAINING_KEYS if key not in threat]


def _validate_field_remaining_group(path: str, threat: dict[str, Any]) -> list[str]:
    """The five field-remaining keys appear together or not at all; each present key is checked."""

    violations = _missing_field_remaining_keys(path, threat)
    violations.extend(
        f"{path}.{field} has invalid value"
        for field, expected in _THREAT_ENUM_FIELDS.items()
        if field in threat and threat[field] != expected
    )
    violations.extend(
        f"{path}.{field} has invalid type"
        for field, is_valid in _FIELD_REMAINING_TYPE_CHECKS.items()
        if field in threat and not is_valid(threat[field])
    )
    return violations


def _validate_vip_vs_field_leverage(path: str, rows: Any) -> list[str]:
    if not isinstance(rows, list):
        return [f"{path}.vip_vs_field_leverage has invalid type"]
    violations: list[str] = []
    for index, row in enumerate(rows):
        row_path = f"{path}.vip_vs_field_leverage[{index}]"
        if not isinstance(row, dict):
            violations.append(f"{row_path} must be an object")
            continue
        violations.extend(
            f"{row_path}.{field} is required"
            for field in _LEVERAGE_STRING_FIELDS
            if not _is_non_empty_string(row.get(field))
        )
        violations.extend(
            f"{row_path}.{field} has invalid type"
            for field in _LEVERAGE_NUMBER_FIELDS
            if not _is_finite_number(row.get(field))
        )
        violations.extend(_validate_partial_flag(row_path, row))
    return violations
