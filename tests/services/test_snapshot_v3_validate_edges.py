"""Malformed-input edges of the snapshot envelope validator, through its public entry points."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

from dk_results.services.snapshot_v3.validate import collect_presence_warnings, validate_v3_envelope

_STAMP = "2026-02-25T10:00:00Z"


def _envelope() -> dict[str, Any]:
    return {
        "schema_version": 3,
        "snapshot_at": _STAMP,
        "generated_at": _STAMP,
        "sports": {
            "nba": {
                "status": "ok",
                "updated_at": _STAMP,
                "players": [{"name": "A", "player_key": "nba:1"}],
                "primary_contest": {
                    "contest_id": "1",
                    "contest_key": "nba:1",
                    "selection_reason": {"mode": "explicit_id"},
                    "selected_at": _STAMP,
                },
                "contests": [
                    {
                        "contest_id": "1",
                        "contest_key": "nba:1",
                        "name": "NBA Contest",
                        "sport": "nba",
                        "contest_type": "classic",
                        "start_time": _STAMP,
                        "state": "live",
                        "entry_fee_cents": 1000,
                        "prize_pool_cents": 200000,
                        "currency": "USD",
                        "max_entries": 229,
                    }
                ],
            }
        },
    }


def _with(edits: dict[str, Any]) -> dict[str, Any]:
    """An envelope with each dotted path (digits index lists) set to a value."""
    payload = deepcopy(_envelope())
    for dotted, value in edits.items():
        *parents, leaf = dotted.split(".")
        node: Any = payload
        for part in parents:
            node = node[int(part)] if part.isdigit() else node[part]
        node[int(leaf) if leaf.isdigit() else leaf] = value
    return payload


_CONTEST = "sports.nba.contests.0"
_VIP_ROW = {"display_name": "vip1", "contest_id": "1", "players_live": []}

MALFORMED = {
    "schema_version": ({"schema_version": 2}, "schema_version must equal 3"),
    "snapshot_at": ({"snapshot_at": "nope"}, "snapshot_at must be a valid ISO timestamp"),
    "generated_at": ({"generated_at": "nope"}, "generated_at must be a valid ISO timestamp"),
    "sports_not_object": ({"sports": "nba"}, "sports must be an object"),
    "sport_not_object": ({"sports.nba": "nba"}, "sports.nba must be an object"),
    "contest_not_object": ({"sports.nba.contests": ["x"]}, "sports.nba.contests[0] must be an object"),
    "sport_status_required": ({"sports.nba.status": None}, "sports.nba.status is required"),
    "sport_players_type": ({"sports.nba.players": "x"}, "sports.nba.players has invalid type"),
    "sport_updated_at": ({"sports.nba.updated_at": "nope"}, "sports.nba.updated_at must be a valid ISO timestamp"),
    "sport_status_value": ({"sports.nba.status": "weird"}, "sports.nba.status has invalid value"),
    "sport_contests_type": ({"sports.nba.contests": "x"}, "sports.nba.contests has invalid type"),
    "primary_not_object": ({"sports.nba.primary_contest": "x"}, "sports.nba.primary_contest is required"),
    "max_entries_per_user": (
        {f"{_CONTEST}.max_entries_per_user": "x"},
        "sports.nba.contests[0].max_entries_per_user has invalid type",
    ),
    "vip_lineups_type": ({f"{_CONTEST}.vip_lineups": "x"}, "sports.nba.contests[0].vip_lineups has invalid type"),
    "players_live_type": (
        {f"{_CONTEST}.vip_lineups": [{**_VIP_ROW, "players_live": "x"}]},
        "sports.nba.contests[0].vip_lineups[0].players_live has invalid type",
    ),
    "players_live_slot_type": (
        {f"{_CONTEST}.vip_lineups": [{**_VIP_ROW, "players_live": ["x"]}]},
        "sports.nba.contests[0].vip_lineups[0].players_live[0] must be an object",
    ),
    "players_live_name_required": (
        {f"{_CONTEST}.vip_lineups": [{**_VIP_ROW, "players_live": [{"slot": "UTIL"}]}]},
        "sports.nba.contests[0].vip_lineups[0].players_live[0].player_name is required",
    ),
    "standings_row_type": (
        {f"{_CONTEST}.standings": ["x"]},
        "sports.nba.contests[0].standings[0] must be an object",
    ),
    "ownership_summary_type": (
        {f"{_CONTEST}.metrics": {"ownership_summary": "x"}},
        "sports.nba.contests[0].metrics.ownership_summary has invalid type",
    ),
    "leverage_row_type": (
        {f"{_CONTEST}.metrics": {"threat": {"vip_vs_field_leverage": ["x"]}}},
        "sports.nba.contests[0].metrics.threat.vip_vs_field_leverage[0] must be an object",
    ),
}


@pytest.mark.parametrize(("edits", "expected"), MALFORMED.values(), ids=MALFORMED.keys())
def test_validate_v3_envelope_reports_each_malformed_edge(edits: dict[str, Any], expected: str) -> None:
    assert expected in validate_v3_envelope(_with(edits))


def test_validate_v3_envelope_prefixes_contract_messages_for_malformed_metric_rows() -> None:
    payload = _with(
        {
            f"{_CONTEST}.metrics": {
                "distance_to_cash": {"per_vip": [{}]},
                "threat": {"top_swing_players": [{}]},
            }
        }
    )

    violations = validate_v3_envelope(payload)

    assert sorted(v for v in violations if "metrics" in v) == [
        "sports.nba.contests[0].metrics.distance_to_cash.per_vip[0].points_delta is required",
        "sports.nba.contests[0].metrics.threat.top_swing_players[0].player_key is required",
        "sports.nba.contests[0].metrics.threat.top_swing_players[0].player_name is required",
    ]


def test_validate_v3_envelope_skips_null_sections_and_non_object_known_player_rows() -> None:
    swing = {"player_key": "nba:1", "player_name": "A", "ownership_remaining_pct": 1.0}
    payload = _with(
        {
            f"{_CONTEST}.standings": None,
            "sports.nba.players": ["x", {"name": "A", "player_key": "nba:1"}],
            f"{_CONTEST}.metrics": {"threat": {"top_swing_players": [swing]}},
        }
    )

    assert validate_v3_envelope(payload) == ["sports.nba.players[0] must be an object"]


def test_collect_presence_warnings_ignores_a_payload_without_a_sports_object() -> None:
    assert collect_presence_warnings({"sports": "nba"}) == []
