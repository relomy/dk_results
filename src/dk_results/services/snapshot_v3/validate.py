"""Validation helpers for snapshot schema v3."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from dk_results.services.snapshot_v3.contracts import (
    SCHEMA_VERSION,
    validate_distance_to_cash_rows,
    validate_single_contest,
    validate_top_swing_players,
)


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
    return violations


def _validate_contest_id_coherence(sport: str, contest: dict[str, Any]) -> list[str]:
    violations: list[str] = []
    contest_id = str(contest.get("contest_id") or "")

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


def _collect_known_player_keys(sport_payload: dict[str, Any], contest: dict[str, Any]) -> set[str]:
    keys: set[str] = set()

    sport_players = sport_payload.get("players")
    if isinstance(sport_players, list):
        for row in sport_players:
            if not isinstance(row, dict):
                continue
            player_key = row.get("player_key")
            if _is_non_empty_string(player_key):
                keys.add(str(player_key))

    players = contest.get("players")
    if isinstance(players, list):
        for row in players:
            if not isinstance(row, dict):
                continue
            player_key = row.get("player_key")
            if _is_non_empty_string(player_key):
                keys.add(str(player_key))

    vip_lineups = contest.get("vip_lineups")
    if isinstance(vip_lineups, list):
        for vip_row in vip_lineups:
            if not isinstance(vip_row, dict):
                continue
            slots = vip_row.get("players_live")
            if not isinstance(slots, list):
                slots = vip_row.get("slots")
            if not isinstance(slots, list):
                slots = vip_row.get("lineup")
            if not isinstance(slots, list):
                slots = vip_row.get("players")
            if not isinstance(slots, list):
                continue
            for slot in slots:
                if not isinstance(slot, dict):
                    continue
                player_key = slot.get("player_key")
                if _is_non_empty_string(player_key):
                    keys.add(str(player_key))

    return keys


def _validate_train_cluster_references(sport: str, contest: dict[str, Any]) -> list[str]:
    violations: list[str] = []

    standings = contest.get("standings")
    if not isinstance(standings, list):
        return violations
    known_entry_keys = {
        str(row.get("entry_key"))
        for row in standings
        if isinstance(row, dict) and row.get("entry_key") not in (None, "")
    }
    if not known_entry_keys:
        return violations

    train_clusters = contest.get("train_clusters")
    if not isinstance(train_clusters, list):
        return violations
    for cluster_index, cluster in enumerate(train_clusters):
        if not isinstance(cluster, dict):
            continue
        for entry_key in list(cluster.get("entry_keys") or []):
            if entry_key in (None, ""):
                continue
            normalized = str(entry_key)
            if normalized not in known_entry_keys:
                violations.append(
                    f"sports.{sport}.contests[0].train_clusters[{cluster_index}].entry_keys "
                    f"contains unknown standings entry_key {normalized}"
                )
        sample_entries = cluster.get("sample_entries")
        if not isinstance(sample_entries, list):
            continue
        for sample_index, sample in enumerate(sample_entries):
            if not isinstance(sample, dict):
                continue
            sample_key = sample.get("entry_key")
            if sample_key in (None, ""):
                continue
            if str(sample_key) not in known_entry_keys:
                violations.append(
                    f"sports.{sport}.contests[0].train_clusters[{cluster_index}].sample_entries[{sample_index}]."
                    "entry_key must match standings entry_key"
                )

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
        sport_name = str(sport)
        if not isinstance(sport_payload_raw, dict):
            violations.append(f"sports.{sport_name} must be an object")
            continue

        sport_payload = sport_payload_raw
        single_contest_violations = validate_single_contest(sport_payload)
        if single_contest_violations:
            for message in single_contest_violations:
                violations.append(message.replace("sport_payload.", f"sports.{sport_name}."))
            continue

        contest = sport_payload.get("contests", [])[0]
        if not isinstance(contest, dict):
            violations.append(f"sports.{sport_name}.contests[0] must be an object")
            continue

        violations.extend(_validate_contest_required_fields(sport_name, contest))
        violations.extend(_validate_contest_id_coherence(sport_name, contest))
        violations.extend(_validate_train_cluster_references(sport_name, contest))

        primary_contest = sport_payload.get("primary_contest")
        if not isinstance(primary_contest, dict):
            violations.append(f"sports.{sport_name}.primary_contest is required")
        else:
            if str(primary_contest.get("contest_key") or "") != str(contest.get("contest_key") or ""):
                violations.append(
                    f"sports.{sport_name}.primary_contest.contest_key must match contests[0].contest_key"
                )

        metrics = contest.get("metrics")
        if isinstance(metrics, dict):
            distance_to_cash = metrics.get("distance_to_cash")
            if isinstance(distance_to_cash, dict):
                per_vip = distance_to_cash.get("per_vip")
                if isinstance(per_vip, list):
                    for message in validate_distance_to_cash_rows(per_vip):
                        violations.append(_prefix_contract_path(sport_name, message))

            threat = metrics.get("threat")
            if isinstance(threat, dict):
                top_swing_players = threat.get("top_swing_players")
                if isinstance(top_swing_players, list):
                    for message in validate_top_swing_players(top_swing_players):
                        violations.append(_prefix_contract_path(sport_name, message))

                    known_player_keys = _collect_known_player_keys(sport_payload, contest)
                    seen_player_keys: set[str] = set()
                    for index, row in enumerate(top_swing_players):
                        if not isinstance(row, dict):
                            continue
                        player_key = row.get("player_key")
                        if not _is_non_empty_string(player_key):
                            continue
                        normalized_key = str(player_key)
                        if known_player_keys and normalized_key not in known_player_keys:
                            violations.append(
                                f"sports.{sport_name}.contests[0].metrics.threat.top_swing_players[{index}].player_key "
                                "is not in known contest player set"
                            )
                        if normalized_key in seen_player_keys:
                            violations.append(
                                f"sports.{sport_name}.contests[0].metrics.threat.top_swing_players "
                                f"has duplicate player_key {normalized_key}"
                            )
                            break
                        seen_player_keys.add(normalized_key)

    return violations
