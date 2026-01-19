import datetime

from classes.contest import Contest
from classes.lineup import Lineup
from classes.player import Player
from classes.sport import NFLSport
from classes.user import User


def test_player_post_init_splits_roster_pos_and_casts_salary():
    player = Player("A", "QB", "QB/FLEX", 5500, "NE@NYJ 1:00PM ET", "NE")

    assert player.roster_pos == ["QB", "FLEX"]
    assert player.salary == 5500


def test_player_update_stats_sets_value_and_matchup_info():
    player = Player("A", "QB", "QB", 5000, "NE@NYJ 1:00PM ET", "NE")

    player.update_stats("QB", "12.5%", "25.0")

    assert player.standings_pos == "QB"
    assert player.ownership == 0.125
    assert player.fpts == 25.0
    assert player.value == 5.0
    assert player.matchup_info == "vs. NYJ"


def test_player_update_stats_handles_zero_points():
    player = Player("A", "QB", "QB", 5000, "NE@NYJ 1:00PM ET", "NE")

    player.update_stats("QB", "0%", "0")

    assert player.value == 0


def test_player_get_matchup_info_non_matchup_and_status():
    player = Player("A", "QB", "QB", 5000, "Final", "NE")

    assert player.get_matchup_info() == "Final"

    player.game_info = "GOLF"
    assert player.get_matchup_info() == "GOLF"


def test_player_get_matchup_info_home_team():
    player = Player("A", "QB", "QB", 5000, "NYJ@NE 1:00PM ET", "NE")

    assert player.get_matchup_info() == "at NYJ"


def test_player_writeable_formats_rows():
    player = Player("A", "QB", "QB", 5000, "NE@NYJ 1:00PM ET", "NE")
    player.update_stats("QB", "10%", "20")

    assert player.writeable("NFL") == [
        "QB",
        "A",
        "NE",
        "vs. NYJ",
        5000,
        0.1,
        20.0,
        4.0,
    ]
    assert player.writeable("PGA") == ["QB", "A", 5000, 0.1, 20.0]


def test_player_str_and_repr_smoke():
    player = Player("A", "QB", "QB", 5000, "NE@NYJ 1:00PM ET", "NE")

    assert "Player" in str(player)
    assert "Player(" in repr(player)


def test_user_set_lineup_updates_salary_and_lineup():
    player = Player("A", "QB", "QB", 5000, "NE@NYJ 1:00PM ET", "NE")
    user = User(1, "1", "User", "0", 100.0, "QB A")

    user.set_lineup([player])

    assert user.salary == 45000
    assert user.lineup == [player]


def test_user_set_lineup_obj_updates_salary_and_lineupobj():
    players = {"A": Player("A", "QB", "QB", 5000, "NE@NYJ 1:00PM ET", "NE")}
    lineup = Lineup(NFLSport, players, "QB A")
    user = User(1, "1", "User", "0", 100.0, "QB A")

    user.set_lineup_obj(lineup)

    assert user.salary == 45000
    assert user.lineupobj is lineup


def test_user_str_and_repr_smoke():
    user = User(1, "1", "User", "0", 100.0, "QB A")

    assert "User" in str(user)
    assert "User(" in repr(user)


def test_contest_fields_and_flags_from_dict():
    contest = Contest(
        {
            "sd": "/Date(1700000000000)/",
            "n": " Contest ",
            "id": 123,
            "dg": 10,
            "po": 1000,
            "m": 100,
            "a": 25,
            "ec": 1,
            "mec": 1,
            "attr": {"IsDoubleUp": True, "IsGuaranteed": True, "IsStarred": True},
            "gameType": "Classic",
            "gameTypeId": 1,
        },
        "NFL",
    )

    assert contest.name == "Contest"
    assert contest.id == 123
    assert contest.is_double_up is True
    assert contest.is_guaranteed is True
    assert contest.is_starred is True
    assert isinstance(contest.start_dt, datetime.datetime)


def test_contest_get_dt_from_timestamp_and_str_smoke():
    contest = Contest(
        {
            "sd": "/Date(0)/",
            "n": "Contest",
            "id": 123,
            "dg": 10,
            "po": 1000,
            "m": 100,
            "a": 25,
            "ec": 1,
            "mec": 1,
            "attr": {},
            "gameType": "Classic",
            "gameTypeId": 1,
        },
        "NFL",
    )

    assert contest.get_dt_from_timestamp("/Date(0)/") == datetime.datetime.fromtimestamp(
        0
    )
    assert "Contest" in str(contest)
