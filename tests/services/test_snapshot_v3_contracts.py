from dk_results.services.snapshot_v3.contracts import (
    SCHEMA_VERSION,
    validate_distance_to_cash_rows,
    validate_single_contest,
    validate_top_swing_players,
)


def test_schema_version_is_3() -> None:
    assert SCHEMA_VERSION == 3


def test_single_contest_required_per_sport_payload() -> None:
    violations = validate_single_contest({"contests": [{"contest_key": "nba:1"}]})
    assert violations == []

    assert validate_single_contest({"contests": []}) == ["sport_payload.contests must contain exactly 1 contest"]
    assert validate_single_contest({"contests": [{"contest_key": "nba:1"}, {"contest_key": "nba:2"}]}) == [
        "sport_payload.contests must contain exactly 1 contest"
    ]


def test_top_swing_players_require_player_key_and_player_name() -> None:
    rows = [{"player_key": "nba:123", "player_name": "Jalen Johnson"}]
    assert validate_top_swing_players(rows) == []

    assert validate_top_swing_players([{"player_name": "Jalen Johnson"}]) == [
        "contest.metrics.threat.top_swing_players[0].player_key is required"
    ]
    assert validate_top_swing_players([{"player_key": "nba:123"}]) == [
        "contest.metrics.threat.top_swing_players[0].player_name is required"
    ]


def test_distance_to_cash_rows_require_points_delta() -> None:
    assert validate_distance_to_cash_rows([{"vip_entry_key": "e1", "points_delta": 1.25}]) == []

    assert validate_distance_to_cash_rows([{"vip_entry_key": "e1", "rank_delta": 4}]) == [
        "contest.metrics.distance_to_cash.per_vip[0].points_delta is required"
    ]
