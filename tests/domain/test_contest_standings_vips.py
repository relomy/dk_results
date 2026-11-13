from dk_results.domain.contest_standings import parse_contest_standings
from dk_results.domain.sport import NFLSport


def test_configured_vip_matches_draftkings_name_case_insensitively():
    salary_rows = [
        ["Position", "ID", "Name", "ID2", "Roster Position", "Salary", "Game Info", "TeamAbbrev", "AvgPoints"],
        ["QB", "", "Tom Brady", "", "QB", "7000", "NE@NYJ", "NE", ""],
    ]
    standings_rows = [
        ["rank", "player_id", "name", "pmr", "pts", "lineup_str"],
        ["1", "111", "mIXeDCaSeVip", "0", "150", "QB Tom Brady"],
        ["2", "222", "UntrackedUser", "15", "120", "QB Tom Brady"],
    ]

    standings = parse_contest_standings(NFLSport, salary_rows, standings_rows, positions_paid=1, vips=["MixedCaseVIP"])

    assert [user.name for user in standings.vip_list] == ["mIXeDCaSeVip"]
