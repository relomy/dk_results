import csv
import datetime

import pytest

import classes.results as results_module
from classes.player import Player
from classes.results import Results
from classes.sport import NFLSport


def _sample_salary_rows():
    return [
        [
            "Position",
            "ID",
            "Name",
            "ID2",
            "Roster Position",
            "Salary",
            "Game Info",
            "TeamAbbrev",
            "AvgPoints",
        ],
        ["QB", "", "Tom Brady", "", "QB", "7000", "NE@NYJ", "NE", ""],
        ["RB", "", "Derrick Henry", "", "RB/FLEX", "8000", "TEN@IND", "TEN", ""],
        ["WR", "", "Justin Jefferson", "", "WR/FLEX", "9000", "MIN@GB", "MIN", ""],
        ["TE", "", "Travis Kelce", "", "TE", "7500", "KC@LAC", "KC", ""],
    ]


def _sample_standings_rows():
    return [
        ["rank", "player_id", "name", "pmr", "pts", "lineup_str"],
        [
            "1",
            "111",
            "CashUser",
            "0",
            "150",
            "QB Tom Brady RB Derrick Henry WR Justin Jefferson TE Travis Kelce",
        ],
        [
            "2",
            "222",
            "NonCashUser",
            "15",
            "120",
            "QB Tom Brady RB Derrick Henry WR Justin Jefferson TE Travis Kelce",
        ],
    ]


def test_results_accepts_injected_rows(monkeypatch):
    def _boom(*_args, **_kwargs):
        raise AssertionError("File parsing should not be called when rows injected.")

    monkeypatch.setattr(results_module.Results, "parse_salary_csv", _boom)
    monkeypatch.setattr(results_module.Results, "parse_contest_standings_csv", _boom)

    results = results_module.Results(
        NFLSport,
        contest_id=1,
        salary_csv_fn="unused.csv",
        positions_paid=1,
        salary_rows=_sample_salary_rows(),
        standings_rows=_sample_standings_rows(),
    )

    assert "Tom Brady" in results.players
    assert len(results.users) == 2


def test_results_accepts_iterable_rows():
    salary_rows = iter(_sample_salary_rows())
    standings_rows = iter(_sample_standings_rows())

    results = results_module.Results(
        NFLSport,
        contest_id=1,
        salary_csv_fn="unused.csv",
        positions_paid=1,
        salary_rows=salary_rows,
        standings_rows=standings_rows,
    )

    assert "Tom Brady" in results.players
    assert len(results.users) == 2


def test_results_coerces_string_positions_paid():
    results = results_module.Results(
        NFLSport,
        contest_id=1,
        salary_csv_fn="unused.csv",
        positions_paid="1",
        salary_rows=_sample_salary_rows(),
        standings_rows=_sample_standings_rows(),
    )

    assert results.positions_paid == 1
    assert results.min_rank == 1
    assert results.min_cash_pts == 150.0


def test_results_handles_blank_points_without_type_error():
    standings_rows = [
        ["rank", "player_id", "name", "pmr", "pts", "lineup_str"],
        [
            "1",
            "111",
            "CashUser",
            "0",
            "",
            "QB Tom Brady RB Derrick Henry WR Justin Jefferson TE Travis Kelce",
        ],
    ]

    results = results_module.Results(
        NFLSport,
        contest_id=1,
        salary_csv_fn="unused.csv",
        positions_paid=10,
        salary_rows=_sample_salary_rows(),
        standings_rows=standings_rows,
    )

    assert len(results.users) == 1
    assert results.min_rank == 0
    assert results.min_cash_pts == 1000.0


def test_add_player_to_dict_increments_for_new_and_existing_players():
    results = results_module.Results(
        sport_obj=NFLSport,
        contest_id=1,
        salary_csv_fn="unused.csv",
        positions_paid=1,
        salary_rows=_sample_salary_rows(),
        standings_rows=_sample_standings_rows(),
    )
    player = results.players["Tom Brady"]
    counts: dict[str, int] = {}

    results.add_player_to_dict(player, counts)
    assert counts[player.name] == 1

    results.add_player_to_dict(player, counts)
    assert counts[player.name] == 2


def test_parse_contest_standings_rows_handles_empty_player_stats_columns():
    standings_rows = [
        ["rank", "player_id", "name", "pmr", "pts", "lineup_str"],
        [
            "1",
            "111",
            "NoStatsUser",
            "0",
            "150",
            "QB Tom Brady RB Derrick Henry WR Justin Jefferson TE Travis Kelce",
            "",
            "",
            "",
            "",
        ],
    ]
    results = results_module.Results(
        sport_obj=NFLSport,
        contest_id=1,
        salary_csv_fn="unused.csv",
        positions_paid=1,
        salary_rows=_sample_salary_rows(),
        standings_rows=standings_rows,
    )

    assert len(results.users) == 1


def test_parse_contest_standings_rows_skips_blank_core_rows():
    standings_rows = [
        ["rank", "player_id", "name", "pmr", "pts", "lineup_str"],
        ["1", "111", "UserA", "0", "120", "QB Tom Brady RB Derrick Henry"],
        ["", "", "", "", "", ""],
        ["", " ", " ", "", "", "   "],
    ]
    results = results_module.Results(
        sport_obj=NFLSport,
        contest_id=1,
        salary_csv_fn="unused.csv",
        positions_paid=1,
        salary_rows=_sample_salary_rows(),
        standings_rows=standings_rows,
    )

    assert len(results.users) == 1
    assert results.users[0].name == "UserA"


def test_parse_contest_standings_rows_processes_player_stats_only_rows():
    salary_rows = _sample_salary_rows()
    salary_rows[1][6] = "NE@NYJ 1:00PM ET"
    standings_rows = [
        ["rank", "player_id", "name", "pmr", "pts", "lineup_str", "", "Player", "Roster Position", "%Drafted", "FPTS"],
        ["1", "111", "UserA", "0", "120", "QB Tom Brady RB Derrick Henry"],
        ["", "", "", "", "", "", "", "Tom Brady", "QB", "50.00%", "20"],
    ]
    results = results_module.Results(
        sport_obj=NFLSport,
        contest_id=1,
        salary_csv_fn="unused.csv",
        positions_paid=1,
        salary_rows=salary_rows,
        standings_rows=standings_rows,
    )

    assert len(results.users) == 1
    player = results.players["Tom Brady"]
    assert player.standings_pos == "QB"
    assert player.ownership == 0.5
    assert player.fpts == 20.0


def test_parse_lineup_string_handles_locked_and_unknown_players():
    results = results_module.Results(
        sport_obj=NFLSport,
        contest_id=1,
        salary_csv_fn="unused.csv",
        positions_paid=1,
        salary_rows=_sample_salary_rows(),
        standings_rows=_sample_standings_rows(),
    )
    lineup = results.parse_lineup_string("QB LOCKED RB UnknownPlayer")

    assert len(lineup) == 1
    assert lineup[0].name == "LOCKED 🔒"


def test_vips_are_injected_and_populate_vip_list():
    standings_rows = [
        ["rank", "player_id", "name", "pmr", "pts", "lineup_str"],
        [
            "1",
            "111",
            "vip_user",
            "0",
            "150",
            "QB Tom Brady RB Derrick Henry WR Justin Jefferson TE Travis Kelce",
        ],
        [
            "2",
            "222",
            "other_user",
            "10",
            "120",
            "QB Tom Brady RB Derrick Henry WR Justin Jefferson TE Travis Kelce",
        ],
    ]
    results = results_module.Results(
        NFLSport,
        contest_id=1,
        salary_csv_fn="unused.csv",
        positions_paid=1,
        salary_rows=_sample_salary_rows(),
        standings_rows=standings_rows,
        vips=["vip_user"],
    )

    assert [user.name for user in results.vip_list] == ["vip_user"]


def test_vip_list_empty_when_no_vips_provided():
    results = results_module.Results(
        NFLSport,
        contest_id=1,
        salary_csv_fn="unused.csv",
        positions_paid=1,
        salary_rows=_sample_salary_rows(),
        standings_rows=_sample_standings_rows(),
    )

    assert results.vip_list == []


def test_lineup_built_for_all_rows_when_positions_paid(monkeypatch):
    class CounterLineup:
        calls = 0

        def __init__(self, *_args, **_kwargs):
            CounterLineup.calls += 1
            self.lineup = []

    monkeypatch.setattr(results_module, "Lineup", CounterLineup)

    results_module.Results(
        NFLSport,
        contest_id=1,
        salary_csv_fn="unused.csv",
        positions_paid=1,
        salary_rows=_sample_salary_rows(),
        standings_rows=_sample_standings_rows(),
    )

    assert CounterLineup.calls == 2


def test_lineup_built_for_all_rows_when_no_positions_paid(monkeypatch):
    class CounterLineup:
        calls = 0

        def __init__(self, *_args, **_kwargs):
            CounterLineup.calls += 1
            self.lineup = []

    standings_rows = [
        ["rank", "player_id", "name", "pmr", "pts", "lineup_str"],
        [
            "1",
            "111",
            "aplewandowski",
            "0",
            "150",
            "QB Tom Brady RB Derrick Henry WR Justin Jefferson TE Travis Kelce",
        ],
        [
            "2",
            "222",
            "NonVip",
            "10",
            "120",
            "QB Tom Brady RB Derrick Henry WR Justin Jefferson TE Travis Kelce",
        ],
    ]

    monkeypatch.setattr(results_module, "Lineup", CounterLineup)

    results_module.Results(
        NFLSport,
        contest_id=1,
        salary_csv_fn="unused.csv",
        positions_paid=None,
        salary_rows=_sample_salary_rows(),
        standings_rows=standings_rows,
    )

    assert CounterLineup.calls == 2


def test_lineup_built_when_rows_exist(monkeypatch):
    class CounterLineup:
        calls = 0

        def __init__(self, *_args, **_kwargs):
            CounterLineup.calls += 1
            self.lineup = []

    standings_rows = [
        ["rank", "player_id", "name", "pmr", "pts", "lineup_str"],
        [
            "1",
            "111",
            "NotVip",
            "0",
            "150",
            "QB Tom Brady RB Derrick Henry WR Justin Jefferson TE Travis Kelce",
        ],
    ]

    monkeypatch.setattr(results_module, "Lineup", CounterLineup)

    results_module.Results(
        NFLSport,
        contest_id=1,
        salary_csv_fn="unused.csv",
        positions_paid=None,
        salary_rows=_sample_salary_rows(),
        standings_rows=standings_rows,
    )

    assert CounterLineup.calls == 1


class DummySport:
    name = "NFLShowdown"
    sport_name = "NFLShowdown"
    positions = ["CPT", "FLEX"]


def _salary_rows():
    return [
        [
            "Position",
            "",
            "Name",
            "",
            "Roster Pos",
            "Salary",
            "Game Info",
            "Team",
            "APPG",
        ],
        ["CPT", "", "Captain", "", "CPT", "5000", "AAA@BBB 7:00PM", "AAA", "0"],
        ["FLEX", "", "Final Guy", "", "FLEX", "4000", "Final", "BBB", "0"],
    ]


def _standings_rows():
    return [
        ["Rank", "EntryId", "User", "PMR", "Points", "Lineup"],
        [
            "2",
            "1",
            "VIP",
            "10",
            "5",
            "CPT Captain FLEX Final Guy",
            "",
            "Missing",
            "CPT",
            "50%",
            "10",
        ],
    ]


def test_results_uses_default_salary_filename(monkeypatch):
    captured = {}

    class FixedDateTime(datetime.datetime):
        @classmethod
        def now(cls):
            return cls(2024, 1, 1)

    monkeypatch.setattr("classes.results.datetime", FixedDateTime)

    def fake_parse_salary_csv(self, filename):
        captured["filename"] = filename

    def fake_parse_contest_standings_rows(self, rows):
        return None

    monkeypatch.setattr(Results, "parse_salary_csv", fake_parse_salary_csv)
    monkeypatch.setattr(
        Results, "parse_contest_standings_rows", fake_parse_contest_standings_rows
    )

    Results(DummySport(), 1, "", standings_rows=[])

    assert captured["filename"] == "DKSalaries_NFLShowdown_Monday.csv"


def test_parse_salary_rows_skips_short_rows():
    results = Results(
        DummySport(), 1, "", salary_rows=_salary_rows(), standings_rows=_standings_rows()
    )
    results.parse_salary_rows([[], ["X"]])
    assert "Captain" in results.players


def test_parse_contest_standings_rows_handles_non_cashing_and_showdown():
    results = Results(
        DummySport(),
        1,
        "",
        positions_paid=1,
        salary_rows=_salary_rows(),
        standings_rows=_standings_rows(),
        vips=["VIP"],
    )

    assert results.vip_list
    assert results.non_cashing_users == 1
    assert results.non_cashing_avg_pmr > 0
    assert "Captain" in results.non_cashing_players


def test_get_showdown_captain_percent_prints(capsys):
    results = Results(
        DummySport(), 1, "", salary_rows=_salary_rows(), standings_rows=_standings_rows()
    )
    results.get_showdown_captain_percent("Captain", {"Captain": 1})
    assert "Captain" in capsys.readouterr().out


def test_load_standings(tmp_path):
    path = tmp_path / "standings.csv"
    path.write_text("a,b\n1,2\n")
    results = Results(
        DummySport(), 1, "", salary_rows=_salary_rows(), standings_rows=_standings_rows()
    )
    rows = results.load_standings(str(path))
    assert rows == [["a", "b"], ["1", "2"]]


def test_players_to_values_filters_by_ownership():
    results = Results(
        DummySport(), 1, "", salary_rows=_salary_rows(), standings_rows=_standings_rows()
    )
    results.players["Captain"].ownership = 0.5
    results.players["Final Guy"].ownership = 0.0

    values = results.players_to_values("NFLShowdown")
    assert len(values) == 1


def test_get_players_returns_dict():
    results = Results(
        DummySport(), 1, "", salary_rows=_salary_rows(), standings_rows=_standings_rows()
    )
    assert results.get_players() is results.players


def test_results_parses_files_and_skips_empty_row(tmp_path, monkeypatch):
    class DummySport:
        name = "NFL"
        sport_name = "NFL"
        positions = ["QB"]

    salary_csv = tmp_path / "salary.csv"
    salary_csv.write_text(
        "Position,,Name,,Roster Pos,Salary,Game Info,Team,APPG\n"
        "QB,,Player A,,QB,5000,AAA@BBB 7:00PM,AAA,0\n"
    )

    contests_dir = tmp_path / "contests"
    contests_dir.mkdir()
    standings_file = contests_dir / "contest-standings-1.csv"
    standings_file.write_text(
        "Rank,EntryId,User,PMR,Points,Lineup\n"
        "\n"
        "1,1,User,0,0,QB Player A\n"
    )

    monkeypatch.chdir(tmp_path)

    results = Results(DummySport(), 1, str(salary_csv), standings_rows=None)

    assert "Player A" in results.players
