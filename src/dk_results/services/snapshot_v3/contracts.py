"""Strict contract helpers for snapshot schema v3."""

from __future__ import annotations

from typing import Mapping, Sequence

SCHEMA_VERSION = 3


def validate_single_contest(sport_payload: Mapping[str, object]) -> list[str]:
    contests = sport_payload.get("contests")
    if not isinstance(contests, list) or len(contests) != 1:
        return ["sport_payload.contests must contain exactly 1 contest"]
    return []


def validate_top_swing_players(rows: Sequence[Mapping[str, object]]) -> list[str]:
    violations: list[str] = []
    for index, row in enumerate(rows):
        if not row.get("player_key"):
            violations.append(f"contest.metrics.threat.top_swing_players[{index}].player_key is required")
        if not row.get("player_name"):
            violations.append(f"contest.metrics.threat.top_swing_players[{index}].player_name is required")
    return violations


def validate_distance_to_cash_rows(rows: Sequence[Mapping[str, object]]) -> list[str]:
    violations: list[str] = []
    for index, row in enumerate(rows):
        if "points_delta" not in row:
            violations.append(f"contest.metrics.distance_to_cash.per_vip[{index}].points_delta is required")
    return violations
