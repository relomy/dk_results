"""Validation helpers for snapshot schema v3."""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any

from dk_results.services.snapshot_v3.contracts import (
    SCHEMA_VERSION,
    validate_distance_to_cash_rows,
    validate_single_contest,
    validate_top_swing_players,
)
from dk_results.services.snapshot_v3.derive import TOP_REMAINING_PLAYERS_LIMIT
from dk_results.services.snapshot_v3.normalize import resolve_lineup_slots


def _is_non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_valid_timestamp(value: Any) -> bool:
    if not _is_non_empty_string(value):
        return False
    try:
        datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def _has_type(value: Any, expected: type) -> bool:
    if expected is str:
        return _is_non_empty_string(value)
    if expected is int:
        return isinstance(value, int) and not isinstance(value, bool)
    return isinstance(value, expected)


def _is_finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _prefix_contract_path(sport: str, message: str) -> str:
    return message.replace("contest.", f"sports.{sport}.contests[0].")


def _validate_contest_required_fields(sport: str, contest: dict[str, Any]) -> list[str]:
    violations: list[str] = []
    required_fields: dict[str, type] = {
        "contest_id": str,
        "contest_key": str,
        "name": str,
        "sport": str,
        "contest_type": str,
        "start_time": str,
        "state": str,
        "entry_fee_cents": int,
        "prize_pool_cents": int,
        "currency": str,
        "max_entries": int,
    }
    for field, expected_type in required_fields.items():
        value = contest.get(field)
        if value is None:
            violations.append(f"sports.{sport}.contests[0].{field} is required")
            continue
        if not _has_type(value, expected_type):
            violations.append(f"sports.{sport}.contests[0].{field} has invalid type")
    if contest.get("start_time") is not None and not _is_valid_timestamp(contest["start_time"]):
        violations.append(f"sports.{sport}.contests[0].start_time must be a valid ISO timestamp")
    if contest.get("max_entries_per_user") is not None and not _has_type(contest["max_entries_per_user"], int):
        violations.append(f"sports.{sport}.contests[0].max_entries_per_user has invalid type")
    return violations


def _validate_sport_payload(sport: str, sport_payload: dict[str, Any]) -> list[str]:
    violations: list[str] = []
    required_fields: dict[str, type] = {
        "status": str,
        "updated_at": str,
        "players": list,
        "primary_contest": dict,
        "contests": list,
    }
    for field, expected_type in required_fields.items():
        value = sport_payload.get(field)
        if value is None:
            violations.append(f"sports.{sport}.{field} is required")
        elif not _has_type(value, expected_type):
            violations.append(f"sports.{sport}.{field} has invalid type")

    if isinstance(sport_payload.get("updated_at"), str) and not _is_valid_timestamp(sport_payload["updated_at"]):
        violations.append(f"sports.{sport}.updated_at must be a valid ISO timestamp")
    if isinstance(sport_payload.get("status"), str) and sport_payload["status"] not in {"ok", "stale", "error"}:
        violations.append(f"sports.{sport}.status has invalid value")

    violations.extend(_validate_sport_players(sport, sport_payload.get("players")))
    violations.extend(_validate_sport_contests(sport, sport_payload.get("contests")))
    violations.extend(_validate_primary_contest(sport, sport_payload.get("primary_contest")))
    return violations


def _validate_sport_players(sport: str, players: Any) -> list[str]:
    if not isinstance(players, list):
        return []
    violations: list[str] = []
    for index, row in enumerate(players):
        if not isinstance(row, dict):
            violations.append(f"sports.{sport}.players[{index}] must be an object")
            continue
        for field in ("name", "player_key"):
            if field in row and row[field] is not None and not _is_non_empty_string(row[field]):
                violations.append(f"sports.{sport}.players[{index}].{field} has invalid type")
    return violations


def _validate_sport_contests(sport: str, contests: Any) -> list[str]:
    if not isinstance(contests, list):
        return []
    return [
        f"sports.{sport}.contests[{index}] must be an object"
        for index, row in enumerate(contests)
        if not isinstance(row, dict)
    ]


def _validate_primary_contest(sport: str, primary: Any) -> list[str]:
    if not isinstance(primary, dict):
        return []
    violations = [
        f"sports.{sport}.primary_contest.{field} is required"
        for field in ("contest_id", "contest_key")
        if not _is_non_empty_string(primary.get(field))
    ]
    if "selection_reason" not in primary or not isinstance(primary.get("selection_reason"), dict):
        violations.append(f"sports.{sport}.primary_contest.selection_reason is required")
    if not _is_valid_timestamp(primary.get("selected_at")):
        violations.append(f"sports.{sport}.primary_contest.selected_at must be a valid ISO timestamp")
    return violations


def _validate_list_sections(sport: str, contest: dict[str, Any]) -> list[str]:
    violations: list[str] = []
    for section in ("standings", "vip_lineups", "train_clusters"):
        rows = contest.get(section)
        if rows is None:
            continue
        if not isinstance(rows, list):
            violations.append(f"sports.{sport}.contests[0].{section} has invalid type")
            continue
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                violations.append(f"sports.{sport}.contests[0].{section}[{index}] must be an object")
    return violations


def _validate_dict_sections(sport: str, contest: dict[str, Any]) -> list[str]:
    return [
        f"sports.{sport}.contests[0].{section} has invalid type"
        for section in ("ownership_watchlist", "live_metrics", "metrics")
        if contest.get(section) is not None and not isinstance(contest.get(section), dict)
    ]


def _validate_live_metrics_section(sport: str, contest: dict[str, Any]) -> list[str]:
    live_metrics = contest.get("live_metrics")
    if not isinstance(live_metrics, dict):
        return []
    violations: list[str] = []
    if "updated_at" in live_metrics and not _is_valid_timestamp(live_metrics.get("updated_at")):
        violations.append(f"sports.{sport}.contests[0].live_metrics.updated_at must be a valid ISO timestamp")
    cash_line = live_metrics.get("cash_line")
    if cash_line is not None and not isinstance(cash_line, dict):
        violations.append(f"sports.{sport}.contests[0].live_metrics.cash_line has invalid type")
    if "avg_salary_per_player_remaining" in live_metrics:
        value = live_metrics["avg_salary_per_player_remaining"]
        if not _is_finite_number(value) or value < 0:
            violations.append(
                f"sports.{sport}.contests[0].live_metrics.avg_salary_per_player_remaining has invalid type"
            )
    return violations


def _validate_metrics_section(sport: str, contest: dict[str, Any]) -> list[str]:
    metrics = contest.get("metrics")
    if not isinstance(metrics, dict):
        return []
    violations: list[str] = []
    if "updated_at" in metrics and not _is_valid_timestamp(metrics.get("updated_at")):
        violations.append(f"sports.{sport}.contests[0].metrics.updated_at must be a valid ISO timestamp")
    for section in ("distance_to_cash", "threat", "non_cashing"):
        value = metrics.get(section)
        if value is not None and not isinstance(value, dict):
            violations.append(f"sports.{sport}.contests[0].metrics.{section} has invalid type")
    return violations


def _validate_section_rows(sport: str, contest: dict[str, Any]) -> list[str]:
    return [
        *_validate_list_sections(sport, contest),
        *_validate_dict_sections(sport, contest),
        *_validate_live_metrics_section(sport, contest),
        *_validate_metrics_section(sport, contest),
    ]


def _validate_contest_id_coherence(sport: str, contest: dict[str, Any]) -> list[str]:
    violations: list[str] = []
    contest_id = str(contest.get("contest_id") or "")
    expected_sport = sport.lower()
    if contest.get("sport") != expected_sport:
        violations.append(f"sports.{sport}.contests[0].sport must match sport key")
    if contest.get("contest_key") != f"{expected_sport}:{contest_id}":
        violations.append(f"sports.{sport}.contests[0].contest_key must match sport and contest_id")

    for section_name in ("standings", "vip_lineups", "train_clusters", "players"):
        rows = contest.get(section_name)
        if not isinstance(rows, list):
            continue
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                continue
            row_contest_id = row.get("contest_id")
            if row_contest_id is None:
                continue
            if str(row_contest_id) != contest_id:
                violations.append(
                    f"sports.{sport}.contests[0].{section_name}[{index}].contest_id must match contest_id"
                )
    return violations


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
        _add_player_keys_from_rows(slots, keys)


def _collect_known_player_keys(sport_payload: dict[str, Any], contest: dict[str, Any]) -> set[str]:
    keys: set[str] = set()
    _add_player_keys_from_rows(sport_payload.get("players"), keys)
    _add_player_keys_from_rows(contest.get("players"), keys)
    _add_player_keys_from_vip_lineups(contest.get("vip_lineups"), keys)
    return keys


def _validate_cluster_sample_entries(sport: str, cluster_index: int, cluster: dict[str, Any]) -> list[str]:
    cluster_entry_keys = {
        str(entry_key) for entry_key in list(cluster.get("entry_keys") or []) if entry_key not in (None, "")
    }
    sample_entries = cluster.get("sample_entries")
    if not isinstance(sample_entries, list):
        return []

    violations: list[str] = []
    for sample_index, sample in enumerate(sample_entries):
        if not isinstance(sample, dict):
            continue
        sample_key = sample.get("entry_key")
        if sample_key in (None, ""):
            continue
        if str(sample_key) not in cluster_entry_keys:
            violations.append(
                f"sports.{sport}.contests[0].train_clusters[{cluster_index}].sample_entries[{sample_index}]."
                f"entry_key must match train_clusters[{cluster_index}].entry_keys"
            )
    return violations


def _validate_train_cluster_references(sport: str, contest: dict[str, Any]) -> list[str]:
    train_clusters = contest.get("train_clusters")
    if not isinstance(train_clusters, list):
        return []

    violations: list[str] = []
    for cluster_index, cluster in enumerate(train_clusters):
        if not isinstance(cluster, dict):
            continue
        violations.extend(_validate_cluster_sample_entries(sport, cluster_index, cluster))
    return violations


def validate_v3_envelope(payload: dict[str, Any]) -> list[str]:
    violations: list[str] = []

    if payload.get("schema_version") != SCHEMA_VERSION:
        violations.append("schema_version must equal 3")

    snapshot_at = payload.get("snapshot_at")
    if snapshot_at is None:
        violations.append("snapshot_at is required")
    elif not _is_valid_timestamp(snapshot_at):
        violations.append("snapshot_at must be a valid ISO timestamp")

    generated_at = payload.get("generated_at")
    if generated_at is None:
        violations.append("generated_at is required")
    elif not _is_valid_timestamp(generated_at):
        violations.append("generated_at must be a valid ISO timestamp")

    sports = payload.get("sports")
    if not isinstance(sports, dict):
        violations.append("sports must be an object")
        return violations
    if not sports:
        violations.append("sports must contain at least one sport payload")
        return violations

    for sport, sport_payload_raw in sports.items():
        violations.extend(_validate_sport_entry(str(sport), sport_payload_raw))

    return violations


def _validate_sport_entry(sport: str, sport_payload_raw: Any) -> list[str]:
    if not isinstance(sport_payload_raw, dict):
        return [f"sports.{sport} must be an object"]
    sport_payload = sport_payload_raw
    violations = _validate_sport_payload(sport, sport_payload)
    single_contest_violations = validate_single_contest(sport_payload)
    if single_contest_violations:
        return violations + [
            message.replace("sport_payload.", f"sports.{sport}.") for message in single_contest_violations
        ]
    contest = sport_payload.get("contests", [])[0]
    if not isinstance(contest, dict):
        return violations + [f"sports.{sport}.contests[0] must be an object"]
    violations.extend(_validate_contest_required_fields(sport, contest))
    violations.extend(_validate_section_rows(sport, contest))
    violations.extend(_validate_contest_id_coherence(sport, contest))
    violations.extend(_validate_train_cluster_references(sport, contest))
    violations.extend(_validate_primary_coherence(sport, sport_payload, contest))
    violations.extend(_validate_contest_metrics(sport, sport_payload, contest))
    return violations


def _validate_primary_coherence(sport: str, sport_payload: dict[str, Any], contest: dict[str, Any]) -> list[str]:
    primary = sport_payload.get("primary_contest")
    if not isinstance(primary, dict):
        return [f"sports.{sport}.primary_contest is required"]
    violations = []
    for field in ("contest_id", "contest_key"):
        if str(primary.get(field) or "") != str(contest.get(field) or ""):
            violations.append(f"sports.{sport}.primary_contest.{field} must match contests[0].{field}")
    return violations


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
    non_cashing = metrics.get("non_cashing")
    if isinstance(non_cashing, dict):
        violations.extend(_validate_non_cashing(sport, non_cashing))
    if "ownership_summary" in metrics:
        violations.extend(_validate_ownership_summary(sport, metrics["ownership_summary"]))
    threat = metrics.get("threat")
    if isinstance(threat, dict) and isinstance(threat.get("top_swing_players"), list):
        violations.extend(_validate_top_swing_players(sport, sport_payload, contest, threat["top_swing_players"]))
    if isinstance(threat, dict):
        violations.extend(_validate_threat_field_metrics(sport, threat))
    return violations


def _validate_non_cashing(sport: str, non_cashing: dict[str, Any]) -> list[str]:
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
    if summary.get("source") != "vip_lineup_players":
        violations.append(f"{path}.source must be vip_lineup_players")
    if summary.get("scope") != "vip_lineup":
        violations.append(f"{path}.scope must be vip_lineup")
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
    if "is_partial" not in row:
        violations.append(f"{path}.is_partial is required")
    elif not isinstance(row["is_partial"], bool):
        violations.append(f"{path}.is_partial has invalid type")
    return violations


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
    "leverage_semantics": "positive=unique",
    "field_remaining_scope": "contest_field",
    "field_remaining_source": "contest_standings_mean",
}
_FIELD_REMAINING_KEYS = (*_THREAT_ENUM_FIELDS, "field_remaining_pct", "field_remaining_is_partial")
_LEVERAGE_STRING_FIELDS = ("vip_entry_key", "entry_key", "display_name")
_LEVERAGE_NUMBER_FIELDS = ("vip_remaining_pct", "field_remaining_pct", "uniqueness_delta_pct")


def _validate_threat_field_metrics(sport: str, threat: dict[str, Any]) -> list[str]:
    """Check the field-remaining and VIP-leverage parts of ``metrics.threat``."""

    path = f"sports.{sport}.contests[0].metrics.threat"
    violations: list[str] = []
    if any(key in threat for key in _FIELD_REMAINING_KEYS):
        violations.extend(f"{path}.{key} is required" for key in _FIELD_REMAINING_KEYS if key not in threat)
    if "field_remaining_pct" in threat and not _is_finite_number(threat["field_remaining_pct"]):
        violations.append(f"{path}.field_remaining_pct has invalid type")
    if "field_remaining_is_partial" in threat and not isinstance(threat["field_remaining_is_partial"], bool):
        violations.append(f"{path}.field_remaining_is_partial has invalid type")
    violations.extend(
        f"{path}.{field} has invalid value"
        for field, expected in _THREAT_ENUM_FIELDS.items()
        if field in threat and threat[field] != expected
    )
    if "vip_vs_field_leverage" in threat:
        if "field_remaining_pct" not in threat:
            violations.append(f"{path}.vip_vs_field_leverage requires field_remaining_pct")
        violations.extend(_validate_vip_vs_field_leverage(path, threat["vip_vs_field_leverage"]))
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
    return violations
