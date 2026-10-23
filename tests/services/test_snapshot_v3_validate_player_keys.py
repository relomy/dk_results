"""The known-player-key scan behind the top-swing check of the snapshot validator."""

from dk_results.services.snapshot_v3.validate_metrics import _collect_known_player_keys


def test_collect_known_player_keys_from_sport_players() -> None:
    keys = _collect_known_player_keys({"players": [{"player_key": "nba:1"}]}, {})
    assert keys == {"nba:1"}


def test_collect_known_player_keys_from_contest_players() -> None:
    keys = _collect_known_player_keys({}, {"players": [{"player_key": "nba:2"}]})
    assert keys == {"nba:2"}


def test_collect_known_player_keys_from_vip_lineups_players_live() -> None:
    contest = {"vip_lineups": [{"players_live": [{"player_key": "nba:3"}]}]}
    assert _collect_known_player_keys({}, contest) == {"nba:3"}


def test_collect_known_player_keys_ignores_locked_vip_slots() -> None:
    contest = {"vip_lineups": [{"players_live": [{"player_key": "nba:hidden", "is_locked": True}]}]}
    assert _collect_known_player_keys({}, contest) == set()


def test_collect_known_player_keys_from_vip_lineups_slots_fallback() -> None:
    contest = {"vip_lineups": [{"slots": [{"player_key": "nba:4"}]}]}
    assert _collect_known_player_keys({}, contest) == {"nba:4"}


def test_collect_known_player_keys_from_vip_lineups_lineup_fallback() -> None:
    contest = {"vip_lineups": [{"lineup": [{"player_key": "nba:5"}]}]}
    assert _collect_known_player_keys({}, contest) == {"nba:5"}


def test_collect_known_player_keys_from_vip_lineups_players_fallback() -> None:
    contest = {"vip_lineups": [{"players": [{"player_key": "nba:6"}]}]}
    assert _collect_known_player_keys({}, contest) == {"nba:6"}


def test_collect_known_player_keys_ignores_non_list_and_non_dict_rows() -> None:
    contest = {
        "players": "not-a-list",
        "vip_lineups": ["not-a-dict", {"players_live": "not-a-list", "slots": "also-not-a-list"}],
    }
    assert _collect_known_player_keys({"players": "not-a-list"}, contest) == set()
