import pytest

from dk_results.services.snapshot_v3.derive import (
    derive_avg_salary_per_player_remaining,
    derive_distance_to_cash,
    derive_threat,
)


def test_distance_to_cash_emits_rows_only_when_points_delta_available() -> None:
    raw = {
        "cash_line": {"points": 250.0, "rank": 60},
        "vip_lineups": [
            {
                "vip_entry_key": "v1",
                "entry_key": "e1",
                "display_name": "Vip 1",
                "rank": 55,
                "pts": 251.5,
            },
            {
                "vip_entry_key": "v2",
                "entry_key": "e2",
                "display_name": "Vip 2",
                "rank": 45,
                "pts": None,
            },
        ],
    }

    metric = derive_distance_to_cash(raw)

    assert metric == {
        "cutoff_points": 250.0,
        "per_vip": [
            {
                "vip_entry_key": "v1",
                "entry_key": "e1",
                "display_name": "Vip 1",
                "points_delta": 1.5,
                "rank_delta": 5,
            }
        ],
    }


def test_threat_uses_player_level_source_only() -> None:
    raw = {
        "ownership": {
            "watchlist_entries": [
                {"display_name": "user-a", "ownership_remaining_pct": 120.0},
                {"display_name": "user-b", "ownership_remaining_pct": 110.0},
            ],
            "non_cashing_top_remaining_players": [
                {"player_key": "nba:1", "player_name": "Player A", "ownership_remaining_pct": 80.0},
                {"player_key": "nba:2", "player_name": "Player B", "ownership_remaining_pct": 70.0},
            ],
        },
        "vip_lineups": [],
    }

    threat = derive_threat(raw)

    assert [row["player_name"] for row in threat["top_swing_players"]] == ["Player A", "Player B"]


def test_threat_accepts_rows_without_ownership_remaining_pct() -> None:
    raw = {
        "ownership": {
            "non_cashing_top_remaining_players": [
                {"player_key": "nba:1", "player_name": "Player A"},
            ]
        },
        "vip_lineups": [],
    }

    threat = derive_threat(raw)

    assert threat == {"top_swing_players": [{"player_key": "nba:1", "player_name": "Player A", "vip_count": 0}]}


def test_threat_vip_count_joins_on_player_key_only() -> None:
    raw = {
        "ownership": {
            "non_cashing_top_remaining_players": [
                {"player_key": "nba:1", "player_name": "Player A", "ownership_remaining_pct": 80.0},
            ]
        },
        "vip_lineups": [
            {
                "lineup": [
                    {"player_key": "nba:1", "player_name": "Other Name"},
                ]
            },
            {
                "lineup": [
                    {"player_key": "nba:2", "player_name": "Player A"},
                ]
            },
        ],
    }

    threat = derive_threat(raw)

    assert threat["top_swing_players"][0]["vip_count"] == 1


def test_threat_drops_rows_without_player_key() -> None:
    raw = {
        "ownership": {
            "non_cashing_top_remaining_players": [
                {"player_name": "Player A", "ownership_remaining_pct": 80.0},
            ]
        },
        "vip_lineups": [
            {"players_live": [{"player_name": "Player A"}]},
            {"players": [{"name": "Player A"}]},
        ],
    }

    threat = derive_threat(raw)

    assert threat is None


def test_threat_rejects_duplicate_player_key_rows() -> None:
    raw = {
        "ownership": {
            "non_cashing_top_remaining_players": [
                {"player_key": "nba:1", "player_name": "Player A", "ownership_remaining_pct": 80.0},
                {"player_key": "nba:1", "player_name": "Player A Dup", "ownership_remaining_pct": 70.0},
            ]
        },
        "vip_lineups": [],
    }

    with pytest.raises(ValueError, match="duplicate player_key"):
        derive_threat(raw)


def test_avg_salary_per_player_remaining_uses_slot_weighted_live_slots() -> None:
    raw = {
        "vip_lineups": [
            {
                "lineup": [
                    {"salary": 10000, "is_live": True},
                    {"salary": 5000, "is_live": False},
                    {"salary": 7000, "is_live": True},
                ]
            },
            {
                "lineup": [
                    {"salary": 9000, "is_live": True},
                    {"salary": 4000, "is_live": False},
                ]
            },
        ]
    }

    avg_salary = derive_avg_salary_per_player_remaining(raw)

    assert avg_salary == 8666.67


def test_avg_salary_per_player_remaining_supports_raw_vip_players_shape() -> None:
    raw = {
        "vip_lineups": [
            {
                "players": [
                    {"name": "Player A", "salary": "$10,300", "timeStatus": "In Progress"},
                    {"name": "Player B", "salary": "$7,800", "timeStatus": "0"},
                ]
            },
            {
                "players": [
                    {"name": "Player C", "salary": "$9,300", "timeStatus": "Q3 08:20"},
                ]
            },
        ]
    }

    avg_salary = derive_avg_salary_per_player_remaining(raw)

    assert avg_salary == 9800.0


def test_threat_sort_is_deterministic_for_ties() -> None:
    raw = {
        "ownership": {
            "non_cashing_top_remaining_players": [
                {"player_key": "nba:2", "player_name": "B", "ownership_remaining_pct": 80.0},
                {"player_key": "nba:1", "player_name": "A", "ownership_remaining_pct": 80.0},
            ]
        },
        "vip_lineups": [],
    }

    threat = derive_threat(raw)

    assert [row["player_key"] for row in threat["top_swing_players"]] == ["nba:1", "nba:2"]
