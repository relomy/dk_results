from types import SimpleNamespace

from classes.dfs_sheet_domain import (
    build_values_for_new_vip_lineup,
    build_values_for_vip_lineup,
    data_range_for_sport,
    end_col_for_sport,
    header_range_for_sport,
    lineup_range_for_sport,
    new_lineup_range_for_sport,
)


def test_end_col_for_sport_golf_and_other():
    assert end_col_for_sport("GOLF") == "E"
    assert end_col_for_sport("PGAMain") == "E"
    assert end_col_for_sport("NBA") == "H"


def test_ranges_for_sport():
    assert data_range_for_sport("NBA") == "NBA!A2:H"
    assert header_range_for_sport("NBA") == "NBA!A1:H1"
    assert lineup_range_for_sport("NBA") == "NBA!J3:V61"
    assert new_lineup_range_for_sport("NBA") == "NBA!J3:W999"
    assert new_lineup_range_for_sport("PGAShowdown") == "PGAShowdown!J3:W999"
    assert new_lineup_range_for_sport("PGAWeekend") == "PGAWeekend!J3:W999"


def test_build_values_for_vip_lineup_golf_and_other():
    player = SimpleNamespace(
        name="P1",
        salary=100,
        fpts=10,
        value=1.0,
        ownership=0.1,
        pos="G",
    )
    vip = SimpleNamespace(name="VIP", pmr=1.2, lineup=[player], rank=1, pts=50)

    golf_values = build_values_for_vip_lineup("GOLF", vip)
    nba_values = build_values_for_vip_lineup("NBA", vip)

    assert golf_values[0][:4] == ["VIP", None, "PMR", 1.2]
    assert golf_values[1][0] == "Name"
    assert golf_values[-1][0] == "rank"

    assert nba_values[0][:4] == ["VIP", None, "PMR", 1.2]
    assert nba_values[1][0] == "Pos"
    assert nba_values[-1][0] == "rank"


def test_build_values_for_new_vip_lineup():
    user = {"user": "VIP", "pmr": 1.2, "rank": 2, "salary": 50000, "pts": 300}
    players = [
        {
            "pos": "PG",
            "name": "Alpha",
            "ownership": 0.1,
            "salary": 8000,
            "pts": 50,
            "value": 6.0,
            "rtProj": 52,
            "timeStatus": "7:00",
            "stats": "ok",
            "valueIcon": "fire",
        },
        {
            "pos": "SG",
            "name": "Beta",
            "ownership": 0.2,
            "salary": 7000,
            "pts": 45,
            "value": 5.5,
            "rtProj": 46,
            "timeStatus": "8:00",
            "stats": "ok",
            "valueIcon": "ice",
        },
    ]

    values = build_values_for_new_vip_lineup(user, players)

    assert values[0][:4] == ["VIP", None, "PMR", 1.2]
    assert values[1][:3] == ["Pos", "Name", "Own"]
    assert values[2][1] == "Alpha 🔥"
    assert values[3][1] == "Beta ❄️"
    assert values[-1][0] == "rank"
