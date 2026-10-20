"""Shape checks for a sport payload and its one contest in the snapshot envelope.

Required fields and types, section rows, VIP lineup slots, id coherence between the contest
and its rows, and train-cluster references. ``validate.validate_v3_envelope`` runs them.
"""

from __future__ import annotations

from typing import Any

from dk_results.services.snapshot_v3.validate_values import (
    _has_type,
    _is_finite_number,
    _is_non_empty_string,
    _is_valid_timestamp,
)


def _validate_contest_completed_at(sport: str, contest: dict[str, Any]) -> list[str]:
    if "completed_at" not in contest or _is_valid_timestamp(contest["completed_at"]):
        return []
    return [f"sports.{sport}.contests[0].completed_at must be a valid ISO timestamp"]


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
    violations.extend(_validate_contest_completed_at(sport, contest))
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


def _validate_vip_lineups(sport: str, contest: dict[str, Any]) -> list[str]:
    vip_lineups = contest.get("vip_lineups")
    if not isinstance(vip_lineups, list):
        return []
    return [
        violation
        for index, row in enumerate(vip_lineups)
        if isinstance(row, dict)
        for violation in [
            *_validate_vip_figures(f"sports.{sport}.contests[0].vip_lineups[{index}]", row),
            *_validate_vip_lineup_slots(sport, index, row),
        ]
    ]


def _validate_vip_figures(path: str, row: dict[str, Any]) -> list[str]:
    violations = []
    if "rank" in row and not (isinstance(row["rank"], int) and not isinstance(row["rank"], bool)):
        violations.append(f"{path}.rank has invalid type")
    violations.extend(
        f"{path}.{field} has invalid type"
        for field in ("points", "pmr")
        if field in row and not _is_finite_number(row[field])
    )
    return violations


def _validate_vip_lineup_slots(sport: str, vip_index: int, row: dict[str, Any]) -> list[str]:
    slots = row.get("players_live")
    if slots is None:
        return []
    path = f"sports.{sport}.contests[0].vip_lineups[{vip_index}].players_live"
    if not isinstance(slots, list):
        return [f"{path} has invalid type"]

    return [
        violation
        for slot_index, slot in enumerate(slots)
        for violation in _validate_vip_lineup_slot(f"{path}[{slot_index}]", slot)
    ]


def _validate_vip_lineup_slot(path: str, slot: Any) -> list[str]:
    if not isinstance(slot, dict):
        return [f"{path} must be an object"]
    return [*_validate_vip_slot_identity(path, slot), *_validate_vip_slot_lock(path, slot)]


def _validate_vip_slot_identity(path: str, slot: dict[str, Any]) -> list[str]:
    violations = []
    if not _is_non_empty_string(slot.get("slot")):
        message = "is required" if "slot" not in slot else "has invalid type"
        violations.append(f"{path}.slot {message}")
    if not _is_non_empty_string(slot.get("player_name")):
        violations.append(f"{path}.player_name is required")
    elif slot["player_name"] != slot["player_name"].strip():
        violations.append(f"{path}.player_name must not have leading or trailing whitespace")
    return violations


def _validate_vip_slot_lock(path: str, slot: dict[str, Any]) -> list[str]:
    violations = []
    if "is_locked" in slot and not isinstance(slot["is_locked"], bool):
        violations.append(f"{path}.is_locked has invalid type")
    if slot.get("player_name") == "LOCKED 🔒" and slot.get("is_locked") is not True:
        violations.append(f"{path}.is_locked must be true for locked slot")
    if slot.get("is_locked") is True:
        violations.extend(
            f"{path}.{field} is forbidden for locked slot"
            for field in ("player_key", "salary", "is_live")
            if field in slot
        )
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
    violations.extend(_validate_avg_salary_remaining(sport, live_metrics))
    return violations


def _validate_avg_salary_remaining(sport: str, live_metrics: dict[str, Any]) -> list[str]:
    if "avg_salary_per_player_remaining" not in live_metrics:
        return []
    value = live_metrics["avg_salary_per_player_remaining"]
    if _is_finite_number(value) and value >= 0:
        return []
    return [f"sports.{sport}.contests[0].live_metrics.avg_salary_per_player_remaining has invalid type"]


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
