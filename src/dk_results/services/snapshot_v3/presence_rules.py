"""Presence rules: expectations that a field is filled in a given state.

Unlike the checks in ``validate`` they never block publishing: a broken rule is recorded as a
presence warning, a ``{"path", "rule"}`` object.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, TypedDict

from dk_results.analytics.game_status import classify_game_status


class PresenceRule(StrEnum):
    """The rule ids a presence warning names. The contract keeps ``rule`` an open string, so a new rule is additive."""

    CASHING_ROW_HAS_PAYOUT = "cashing_row_has_payout"
    UNLOCKED_VIP_SLOT_HAS_PLAYER_KEY = "unlocked_vip_slot_has_player_key"
    IN_PROGRESS_PLAYER_HAS_STATS = "in_progress_player_has_stats"


class PresenceWarningRow(TypedDict):
    path: str
    rule: PresenceRule


_IN_PROGRESS_PLAYER_FIELDS = ("stats_text", "rt_projection")


def _presence_warning(path: str, rule: PresenceRule) -> PresenceWarningRow:
    return {"path": path, "rule": rule}


def _indexed_dict_rows(rows: Any) -> list[tuple[int, dict[str, Any]]]:
    return [(index, row) for index, row in enumerate(rows) if isinstance(row, dict)] if isinstance(rows, list) else []


def _cashing_row_warnings(contest_path: str, contest: dict[str, Any]) -> list[PresenceWarningRow]:
    return [
        _presence_warning(f"{contest_path}.standings[{index}].payout_cents", PresenceRule.CASHING_ROW_HAS_PAYOUT)
        for index, row in _indexed_dict_rows(contest.get("standings"))
        if row.get("is_cashing") is True and row.get("payout_cents") is None
    ]


def _unlocked_slot_warnings(contest_path: str, contest: dict[str, Any]) -> list[PresenceWarningRow]:
    warnings: list[PresenceWarningRow] = []
    for vip_index, vip in _indexed_dict_rows(contest.get("vip_lineups")):
        for slot_index, slot in _indexed_dict_rows(vip.get("players_live")):
            if slot.get("is_locked") is not True and slot.get("player_key") is None:
                path = f"{contest_path}.vip_lineups[{vip_index}].players_live[{slot_index}].player_key"
                warnings.append(_presence_warning(path, PresenceRule.UNLOCKED_VIP_SLOT_HAS_PLAYER_KEY))
    return warnings


def _in_progress_player_warnings(sport: str, players: Any) -> list[PresenceWarningRow]:
    return [
        _presence_warning(f"sports.{sport}.players[{index}].{field}", PresenceRule.IN_PROGRESS_PLAYER_HAS_STATS)
        for index, player in _indexed_dict_rows(players)
        if classify_game_status(player.get("game_status")).in_play is True
        for field in _IN_PROGRESS_PLAYER_FIELDS
        if player.get(field) is None
    ]


def _sport_presence_warnings(sport: str, sport_payload: dict[str, Any]) -> list[PresenceWarningRow]:
    warnings = _in_progress_player_warnings(sport, sport_payload.get("players"))
    for index, contest in _indexed_dict_rows(sport_payload.get("contests")):
        contest_path = f"sports.{sport}.contests[{index}]"
        warnings.extend(_cashing_row_warnings(contest_path, contest))
        warnings.extend(_unlocked_slot_warnings(contest_path, contest))
    return warnings


def collect_presence_warnings(payload: dict[str, Any]) -> list[PresenceWarningRow]:
    """Presence rules a snapshot breaks, one ``{"path", "rule"}`` per blank field; never blocks publishing."""
    sports = payload.get("sports")
    if not isinstance(sports, dict):
        return []
    return [
        warning
        for sport, sport_payload in sports.items()
        if isinstance(sport_payload, dict)
        for warning in _sport_presence_warnings(str(sport), sport_payload)
    ]
