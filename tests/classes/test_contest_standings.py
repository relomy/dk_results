import logging

import pytest

from dk_results.classes.contest_standings import (
    ContestStandings,
    parse_contest_standings,
    players_to_values,
)
from dk_results.classes.optimizer import Optimizer
from dk_results.classes.sport import NBASport, NFLSport


def _salary_rows():
    return [
        ["Position", "ID", "Name", "ID2", "Roster Position", "Salary", "Game Info", "TeamAbbrev", "AvgPoints"],
        ["QB", "", "Tom Brady", "", "QB", "7000", "NE@NYJ", "NE", ""],
        ["RB", "", "Derrick Henry", "", "RB/FLEX", "8000", "TEN@IND", "TEN", ""],
        ["WR", "", "Justin Jefferson", "", "WR/FLEX", "9000", "MIN@GB", "MIN", ""],
        ["TE", "", "Travis Kelce", "", "TE", "7500", "KC@LAC", "KC", ""],
    ]


def _standings_rows():
    return [
        ["rank", "player_id", "name", "pmr", "pts", "lineup_str"],
        ["1", "111", "CashUser", "0", "150", "QB Tom Brady RB Derrick Henry WR Justin Jefferson TE Travis Kelce"],
        ["2", "222", "NonCashUser", "15", "120", "QB Tom Brady RB Derrick Henry WR Justin Jefferson TE Travis Kelce"],
    ]


def test_parse_produces_players_and_users():
    standings = parse_contest_standings(NFLSport, _salary_rows(), _standings_rows(), positions_paid=1)
    assert "Tom Brady" in standings.players
    assert len(standings.users) == 2


def test_parse_accepts_iterables():
    standings = parse_contest_standings(
        NFLSport, iter(_salary_rows()), iter(_standings_rows()), positions_paid=1
    )
    assert "Tom Brady" in standings.players
    assert len(standings.users) == 2


def test_cash_line_resolved_from_positions_paid():
    standings = parse_contest_standings(NFLSport, _salary_rows(), _standings_rows(), positions_paid=1)
    assert standings.min_rank == 1
    assert standings.min_cash_pts == 150.0
    assert standings.positions_paid == 1


def test_positions_paid_coerced_from_string():
    standings = parse_contest_standings(NFLSport, _salary_rows(), _standings_rows(), positions_paid="1")
    assert standings.positions_paid == 1
    assert standings.min_rank == 1
    assert standings.min_cash_pts == 150.0


def test_no_cash_line_when_positions_paid_none():
    standings = parse_contest_standings(NFLSport, _salary_rows(), _standings_rows(), positions_paid=None)
    assert standings.min_rank == 0
    assert standings.min_cash_pts == 1000.0


def test_blank_points_row_does_not_crash():
    rows = [
        ["rank", "player_id", "name", "pmr", "pts", "lineup_str"],
        ["1", "111", "CashUser", "0", "", "QB Tom Brady RB Derrick Henry WR Justin Jefferson TE Travis Kelce"],
    ]
    standings = parse_contest_standings(NFLSport, _salary_rows(), rows, positions_paid=10)
    assert len(standings.users) == 1
    assert standings.min_rank == 0


def test_vip_detection():
    rows = [
        ["rank", "player_id", "name", "pmr", "pts", "lineup_str"],
        ["1", "111", "vip_user", "0", "150", "QB Tom Brady RB Derrick Henry WR Justin Jefferson TE Travis Kelce"],
        ["2", "222", "other_user", "10", "120", "QB Tom Brady RB Derrick Henry WR Justin Jefferson TE Travis Kelce"],
    ]
    standings = parse_contest_standings(NFLSport, _salary_rows(), rows, positions_paid=1, vips=["vip_user"])
    assert [u.name for u in standings.vip_list] == ["vip_user"]


def test_empty_vip_list_when_no_vips():
    standings = parse_contest_standings(NFLSport, _salary_rows(), _standings_rows(), positions_paid=1)
    assert standings.vip_list == []


def test_non_cashing_stats():
    standings = parse_contest_standings(NFLSport, _salary_rows(), _standings_rows(), positions_paid=1)
    assert standings.non_cashing_users == 1
    assert standings.non_cashing_avg_pmr > 0


def test_blank_core_rows_skipped():
    rows = [
        ["rank", "player_id", "name", "pmr", "pts", "lineup_str"],
        ["1", "111", "UserA", "0", "120", "QB Tom Brady RB Derrick Henry"],
        ["", "", "", "", "", ""],
        ["", " ", " ", "", "", "   "],
    ]
    standings = parse_contest_standings(NFLSport, _salary_rows(), rows, positions_paid=1)
    assert len(standings.users) == 1
    assert standings.users[0].name == "UserA"


def test_player_stats_rows_update_ownership():
    salary = _salary_rows()
    salary[1][6] = "NE@NYJ 1:00PM ET"
    rows = [
        ["rank", "player_id", "name", "pmr", "pts", "lineup_str", "", "Player", "Roster Position", "%Drafted", "FPTS"],
        ["1", "111", "UserA", "0", "120", "QB Tom Brady RB Derrick Henry"],
        ["", "", "", "", "", "", "", "Tom Brady", "QB", "50.00%", "20"],
    ]
    standings = parse_contest_standings(NFLSport, salary, rows, positions_paid=1)
    player = standings.players["Tom Brady"]
    assert player.standings_pos == "QB"
    assert player.ownership == 0.5
    assert player.fpts == 20.0


def test_ownership_sums_and_positions_combine():
    salary = _salary_rows()
    salary[1][6] = "NE@NYJ 1:00PM ET"
    rows = [
        ["rank", "player_id", "name", "pmr", "pts", "lineup_str", "", "Player", "Roster Position", "%Drafted", "FPTS"],
        ["2", "222", "UserB", "0", "110", "QB Tom Brady RB Derrick Henry", "", "Tom Brady", "QB", "40.00%", "20"],
        ["3", "333", "UserC", "0", "100", "QB Tom Brady RB Derrick Henry", "", "Tom Brady", "FLEX", "25.00%", "20"],
    ]
    standings = parse_contest_standings(NFLSport, salary, rows, positions_paid=1)
    player = standings.players["Tom Brady"]
    assert player.standings_pos == "QB/FLEX"
    assert player.ownership == 0.65


def test_ownership_exceeds_100_logs_warning(caplog):
    salary = _salary_rows()
    salary[1][6] = "NE@NYJ 1:00PM ET"
    rows = [
        ["rank", "player_id", "name", "pmr", "pts", "lineup_str", "", "Player", "Roster Position", "%Drafted", "FPTS"],
        ["1", "111", "UserA", "0", "120", "QB Tom Brady RB Derrick Henry", "", "Tom Brady", "QB", "80.00%", "20"],
        ["2", "222", "UserB", "0", "110", "QB Tom Brady RB Derrick Henry", "", "Tom Brady", "FLEX", "40.00%", "20"],
    ]
    with caplog.at_level(logging.WARNING):
        parse_contest_standings(NFLSport, salary, rows, positions_paid=1)
    assert "Ownership exceeds 100%" in caplog.text
    assert "Tom Brady" in caplog.text


def test_standings_pos_does_not_affect_optimizer_pos():
    salary = _salary_rows()
    salary[1][6] = "NE@NYJ 1:00PM ET"
    rows = [
        ["rank", "player_id", "name", "pmr", "pts", "lineup_str", "", "Player", "Roster Position", "%Drafted", "FPTS"],
        ["1", "111", "UserA", "0", "120", "QB Tom Brady RB Derrick Henry", "", "Tom Brady", "QB", "40.00%", "20"],
        ["2", "222", "UserB", "0", "110", "QB Tom Brady RB Derrick Henry", "", "Tom Brady", "FLEX", "25.00%", "20"],
    ]
    standings = parse_contest_standings(NFLSport, salary, rows, positions_paid=1)
    tom = standings.players["Tom Brady"]
    assert tom.standings_pos == "QB/FLEX"
    assert tom.pos == "QB"
    optimizer = Optimizer(NFLSport, standings.players)
    selected = optimizer.create_decision_variables()
    assert ("Tom Brady", "QB") in selected
    assert ("Tom Brady", "FLEX") not in selected


def test_nba_dual_position_player():
    salary = [
        ["Position", "ID", "Name", "ID2", "Roster Position", "Salary", "Game Info", "TeamAbbrev", "AvgPoints"],
        ["PG/SG", "", "Combo Guard", "", "PG/SG/G/UTIL", "7000", "AAA@BBB 7:00PM ET", "AAA", ""],
    ]
    rows = [
        ["rank", "player_id", "name", "pmr", "pts", "lineup_str", "", "Player", "Roster Position", "%Drafted", "FPTS"],
        ["1", "111", "UserA", "0", "120", "PG Combo Guard", "", "Combo Guard", "PG", "40.00%", "20"],
        ["2", "222", "UserB", "0", "110", "SG Combo Guard", "", "Combo Guard", "SG", "20.00%", "20"],
    ]
    standings = parse_contest_standings(NBASport, salary, rows, positions_paid=1)
    combo = standings.players["Combo Guard"]
    assert combo.pos == "PG/SG"
    assert combo.standings_pos == "PG/SG"
    values = players_to_values(standings.players, "NBA")
    combo_row = next(r for r in values if r[1] == "Combo Guard")
    assert combo_row[0] == "PG/SG"
    optimizer = Optimizer(NBASport, standings.players)
    selected = optimizer.create_decision_variables()
    assert ("Combo Guard", "PG") in selected
    assert ("Combo Guard", "SG") in selected


def test_players_to_values_filters_zero_ownership():
    standings = parse_contest_standings(NFLSport, _salary_rows(), _standings_rows(), positions_paid=1)
    standings.players["Tom Brady"].ownership = 0.5
    standings.players["Derrick Henry"].ownership = 0.0
    values = players_to_values(standings.players, "NFL")
    names = [r[1] for r in values]
    assert "Tom Brady" in names
    assert "Derrick Henry" not in names


def test_players_to_values_sorted_by_ownership():
    salary = _salary_rows()
    salary[1][6] = "NE@NYJ 1:00PM ET"
    rows = [
        ["rank", "player_id", "name", "pmr", "pts", "lineup_str", "", "Player", "Roster Position", "%Drafted", "FPTS"],
        ["2", "222", "UserB", "0", "110", "QB Tom Brady RB Derrick Henry", "", "Tom Brady", "QB", "40.00%", "20"],
        ["3", "333", "UserC", "0", "100", "QB Tom Brady RB Derrick Henry", "", "Tom Brady", "FLEX", "25.00%", "20"],
    ]
    standings = parse_contest_standings(NFLSport, salary, rows, positions_paid=1)
    values = players_to_values(standings.players, "NFL")
    tom = next(r for r in values if r[1] == "Tom Brady")
    assert tom[0] == "QB"


class DummyShowdownSport:
    name = "NFLShowdown"
    sport_name = "NFLShowdown"
    positions = ["CPT", "FLEX"]


def _showdown_salary():
    return [
        ["Position", "", "Name", "", "Roster Pos", "Salary", "Game Info", "Team", "APPG"],
        ["CPT", "", "Captain", "", "CPT", "5000", "AAA@BBB 7:00PM", "AAA", "0"],
        ["FLEX", "", "Final Guy", "", "FLEX", "4000", "Final", "BBB", "0"],
    ]


def _showdown_standings():
    return [
        ["Rank", "EntryId", "User", "PMR", "Points", "Lineup"],
        ["2", "1", "VIP", "10", "5", "CPT Captain FLEX Final Guy", "", "Missing", "CPT", "50%", "10"],
    ]


def test_showdown_non_cashing_and_vip():
    standings = parse_contest_standings(
        DummyShowdownSport(),
        _showdown_salary(),
        _showdown_standings(),
        positions_paid=1,
        vips=["VIP"],
    )
    assert standings.vip_list
    assert standings.non_cashing_users == 1
    assert standings.non_cashing_avg_pmr > 0
    assert "Captain" in standings.non_cashing_players


def test_contest_standings_is_frozen():
    standings = parse_contest_standings(NFLSport, _salary_rows(), _standings_rows(), positions_paid=1)
    with pytest.raises(Exception):
        standings.min_rank = 99
