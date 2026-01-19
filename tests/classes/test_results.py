import pytest

import classes.results as results_module
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
