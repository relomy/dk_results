import logging

import pytest
from dfs_common.sheets import NumberFormat

from dk_results.analytics.lineup_solver import PulpCbcSolver
from dk_results.domain.contest_standings import (
    parse_contest_standings,
    players_to_values,
)
from dk_results.domain.dfs_sheet_domain import CellFormat
from dk_results.domain.sport import GolfSport, NBASport, NFLSport


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


def test_parse_accepts_salary_rows_with_additional_columns():
    salary_rows = [
        [
            "Position",
            "Name + ID",
            "Name",
            "ID",
            "Roster Position",
            "Salary",
            "Game Info",
            "TeamAbbrev",
            "AvgPointsPerGame",
            "Status",
            "Starting",
        ],
        [
            "QB",
            "Tom Brady (123)",
            "Tom Brady",
            "123",
            "QB",
            "7000",
            "NE@NYJ",
            "NE",
            "10",
            "",
            "YES",
        ],
    ]

    standings_rows = [
        ["rank", "player_id", "name", "pmr", "pts", "lineup_str"],
        ["1", "111", "CashUser", "0", "150", "QB Tom Brady"],
    ]

    standings = parse_contest_standings(NFLSport, salary_rows, standings_rows, positions_paid=1)

    assert standings.players["Tom Brady"].salary == 7000


def test_parse_accepts_salary_csv_with_utf8_bom():
    salary_rows = _salary_rows()
    salary_rows[0][0] = "\ufeffPosition"

    standings = parse_contest_standings(NFLSport, salary_rows, _standings_rows(), positions_paid=1)

    assert "Tom Brady" in standings.players


def test_parse_reports_all_missing_salary_columns():
    salary_rows = [["Position"], ["QB"]]

    with pytest.raises(ValueError, match="missing required columns") as exc_info:
        parse_contest_standings(NFLSport, salary_rows, _standings_rows(), positions_paid=1)

    message = str(exc_info.value)
    assert "name" in message
    assert "roster position" in message
    assert "salary" in message
    assert "game info" in message
    assert "team" in message


def test_parse_accepts_iterables():
    standings = parse_contest_standings(NFLSport, iter(_salary_rows()), iter(_standings_rows()), positions_paid=1)
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


def test_invalid_rank_and_points_are_retained_as_unresolved_values():
    rows = [
        ["rank", "player_id", "name", "pmr", "pts", "lineup_str"],
        ["not-a-rank", "111", "UserA", "0", "not-points", "QB Tom Brady"],
    ]

    standings = parse_contest_standings(NFLSport, _salary_rows(), rows, positions_paid=1)

    assert standings.users[0].rank is None
    assert standings.users[0].pts is None
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


def test_locked_slots_are_not_added_to_non_cashing_player_stats():
    rows = [
        ["rank", "player_id", "name", "pmr", "pts", "lineup_str"],
        ["1", "111", "CashUser", "0", "150", "QB LOCKED RB Derrick Henry"],
        ["2", "222", "NonCashUser", "15", "120", "QB LOCKED RB Derrick Henry"],
    ]

    standings = parse_contest_standings(NFLSport, _salary_rows(), rows, positions_paid=1)

    assert standings.non_cashing_players == {"Derrick Henry": 1}


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
    selected = PulpCbcSolver()._create_decision_variables(standings.players)
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
    values, _format_plan = players_to_values(standings.players, "NBA")
    combo_row = next(r for r in values if r[1] == "Combo Guard")
    assert combo_row[0] == "PG/SG"
    selected = PulpCbcSolver()._create_decision_variables(standings.players)
    assert ("Combo Guard", "PG") in selected
    assert ("Combo Guard", "SG") in selected


def test_players_to_values_filters_zero_ownership():
    standings = parse_contest_standings(NFLSport, _salary_rows(), _standings_rows(), positions_paid=1)
    standings.players["Tom Brady"].ownership = 0.5
    standings.players["Derrick Henry"].ownership = 0.0
    values, _format_plan = players_to_values(standings.players, "NFL")
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
    values, _format_plan = players_to_values(standings.players, "NFL")
    tom = next(r for r in values if r[1] == "Tom Brady")
    assert tom[0] == "QB"


def test_players_to_values_format_plan_tags_salary_column():
    standings = parse_contest_standings(NFLSport, _salary_rows(), _standings_rows(), positions_paid=1)
    standings.players["Tom Brady"].ownership = 0.5
    standings.players["Derrick Henry"].ownership = 0.5
    values, format_plan = players_to_values(standings.players, "NFL")

    assert len(values) == 2
    # Player.writeable for non-PGA sports: [pos, name, team, matchup, salary, own, fpts, value]
    assert format_plan == [
        CellFormat(row=0, col=5, number_format=NumberFormat.PERCENT),
        CellFormat(row=0, col=4, number_format=NumberFormat.CURRENCY),
        CellFormat(row=0, col=6, number_format=NumberFormat.DECIMAL(1)),
        CellFormat(row=0, col=7, number_format=NumberFormat.DECIMAL(1)),
        CellFormat(row=1, col=5, number_format=NumberFormat.PERCENT),
        CellFormat(row=1, col=4, number_format=NumberFormat.CURRENCY),
        CellFormat(row=1, col=6, number_format=NumberFormat.DECIMAL(1)),
        CellFormat(row=1, col=7, number_format=NumberFormat.DECIMAL(1)),
    ]


def test_players_to_values_format_plan_uses_pga_salary_column():
    salary_rows = [
        ["Position", "ID", "Name", "ID2", "Roster Position", "Salary", "Game Info", "TeamAbbrev", "AvgPoints"],
        ["G", "", "Golfer One", "", "G", "9000", "PGA Tour", "PGA", ""],
    ]
    standings_rows = [
        ["rank", "player_id", "name", "pmr", "pts", "lineup_str", "", "Player", "Roster Position", "%Drafted", "FPTS"],
        ["1", "111", "UserA", "0", "100", "G Golfer One", "", "Golfer One", "G", "50.00%", "80"],
    ]

    standings = parse_contest_standings(GolfSport, salary_rows, standings_rows, positions_paid=1)
    values, format_plan = players_to_values(standings.players, "PGA")

    assert values[0][2] == 9000
    # Player.writeable for PGA/GOLF: [pos, name, salary, own, fpts] — no Value column.
    assert format_plan == [
        CellFormat(row=0, col=3, number_format=NumberFormat.PERCENT),
        CellFormat(row=0, col=2, number_format=NumberFormat.CURRENCY),
        CellFormat(row=0, col=4, number_format=NumberFormat.DECIMAL(1)),
    ]


class DummyShowdownSport:
    name = "NFLShowdown"
    positions = ("CPT", "FLEX")


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
        DummyShowdownSport,
        _showdown_salary(),
        _showdown_standings(),
        positions_paid=1,
        vips=["VIP"],
    )
    assert standings.vip_list
    assert standings.non_cashing_users == 1
    assert standings.non_cashing_avg_pmr > 0
    assert "Captain" in standings.non_cashing_players


def _showdown_salary_with_dst():
    # Trimmed from a real DKSalaries_NFLShowdown export: a skill player plus a
    # DST, each present twice (once priced for CPT, once for FLEX), which is
    # how DraftKings lists every showdown-eligible player.
    return [
        [
            "Position",
            "Name + ID",
            "Name",
            "ID",
            "Roster Position",
            "Salary",
            "Game Info",
            "TeamAbbrev",
            "AvgPointsPerGame",
        ],
        ["QB", "Josh Allen (1)", "Josh Allen", "1", "CPT", "17100", "Final", "BUF", "38.7"],
        ["QB", "Josh Allen (2)", "Josh Allen", "2", "FLEX", "11400", "Final", "BUF", "38.7"],
        ["DST", "Lions (3)", "Lions", "3", "CPT", "5100", "Final", "DET", "10"],
        ["DST", "Lions (4)", "Lions", "4", "FLEX", "3400", "Final", "DET", "10"],
    ]


def _showdown_standings_with_trailing_space():
    # Trimmed from the real contest-standings-195677858.csv: DraftKings ends
    # the Lineup field with a trailing space after its last slot.
    return [
        ["Rank", "EntryId", "EntryName", "TimeRemaining", "Points", "Lineup"],
        ["1", "1", "dlmurray24", "0", "158.1", "CPT Josh Allen FLEX Lions "],
    ]


def test_showdown_resolves_dst_in_last_flex_slot_with_trailing_space():
    standings = parse_contest_standings(
        DummyShowdownSport,
        _showdown_salary_with_dst(),
        _showdown_standings_with_trailing_space(),
        positions_paid=1,
    )

    user = standings.users[0]
    assert [slot.pos for slot in user.lineupobj.lineup] == ["CPT", "FLEX"]
    assert [slot.name for slot in user.lineupobj.lineup] == ["Josh Allen", "Lions"]


def test_showdown_resolves_dst_in_captain_slot():
    standings_rows = [
        ["Rank", "EntryId", "EntryName", "TimeRemaining", "Points", "Lineup"],
        ["1", "1", "dlmurray24", "0", "158.1", "CPT Lions FLEX Josh Allen "],
    ]

    standings = parse_contest_standings(
        DummyShowdownSport,
        _showdown_salary_with_dst(),
        standings_rows,
        positions_paid=1,
    )

    user = standings.users[0]
    assert [slot.pos for slot in user.lineupobj.lineup] == ["CPT", "FLEX"]
    assert [slot.name for slot in user.lineupobj.lineup] == ["Lions", "Josh Allen"]


def test_showdown_resolves_multi_word_name_in_trailing_space_last_slot():
    # The trailing-space bug isn't specific to short, single-word DST names —
    # confirm a multi-word player name in the last slot survives the same way.
    salary_rows = [
        *_showdown_salary_with_dst(),
        ["WR", "Amon-Ra St. Brown (5)", "Amon-Ra St. Brown", "5", "CPT", "15600", "Final", "DET", "28.7"],
        ["WR", "Amon-Ra St. Brown (6)", "Amon-Ra St. Brown", "6", "FLEX", "10400", "Final", "DET", "28.7"],
    ]
    standings_rows = [
        ["Rank", "EntryId", "EntryName", "TimeRemaining", "Points", "Lineup"],
        ["1", "1", "dlmurray24", "0", "158.1", "CPT Josh Allen FLEX Amon-Ra St. Brown "],
    ]

    standings = parse_contest_standings(
        DummyShowdownSport,
        salary_rows,
        standings_rows,
        positions_paid=1,
    )

    user = standings.users[0]
    assert [slot.pos for slot in user.lineupobj.lineup] == ["CPT", "FLEX"]
    assert [slot.name for slot in user.lineupobj.lineup] == ["Josh Allen", "Amon-Ra St. Brown"]


def test_classic_nfl_resolves_trailing_space_on_last_dst_slot():
    # The trailing-space bug applies to any sport's last roster slot, not
    # just Showdown's FLEX/CPT — classic NFL's last slot is DST.
    salary_rows = [
        *_salary_rows(),
        ["DST", "", "Bears", "", "DST", "3000", "CHI@GB", "CHI", ""],
    ]
    standings_rows = [
        ["rank", "player_id", "name", "pmr", "pts", "lineup_str"],
        [
            "1",
            "111",
            "CashUser",
            "0",
            "150",
            "QB Tom Brady RB Derrick Henry RB Derrick Henry WR Justin Jefferson "
            "WR Justin Jefferson WR Justin Jefferson TE Travis Kelce FLEX Travis Kelce DST Bears ",
        ],
    ]

    standings = parse_contest_standings(NFLSport, salary_rows, standings_rows, positions_paid=1)

    user = standings.users[0]
    assert user.lineupobj.lineup[-1].pos == "DST"
    assert user.lineupobj.lineup[-1].name == "Bears"


def test_contest_standings_is_frozen():
    standings = parse_contest_standings(NFLSport, _salary_rows(), _standings_rows(), positions_paid=1)
    with pytest.raises(Exception):
        standings.min_rank = 99


def test_vip_log_uses_vip_user_format(caplog):
    import logging

    # Need a sport that has players with position "G" for golf-like behavior,
    # or just use NFLSport with the existing _salary_rows() / _standings_rows() helpers.
    # Use NFLSport and mark "CashUser" as a VIP.
    with caplog.at_level(logging.DEBUG):
        parse_contest_standings(
            NFLSport,
            _salary_rows(),
            _standings_rows(),
            positions_paid=1,
            vips=["CashUser"],
        )
    messages = [r.message for r in caplog.records]
    assert any("vip_user" in m and "name=CashUser" in m and "salary_rem=" in m for m in messages)
    assert not any(m.startswith("found VIP") for m in messages)
    assert not any("VIP: [User]" in m for m in messages)


def test_non_cashing_log_uses_key_value_format(caplog):
    import logging

    with caplog.at_level(logging.DEBUG):
        parse_contest_standings(NFLSport, _salary_rows(), _standings_rows(), positions_paid=1)
    messages = [r.message for r in caplog.records]
    assert any(m.startswith("non_cashing") and "users=" in m and "total_pmr=" in m for m in messages)
    assert not any("non_cashing:" in m for m in messages)
