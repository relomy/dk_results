from dfs_common.sheets import NumberFormat

from dk_results.domain.dfs_sheet_domain import (
    CellFormat,
    RangeOrigin,
    build_values_for_vip_lineup,
    data_range_for_sport,
    end_col_for_sport,
    header_range_for_sport,
    lineup_range_for_sport,
    parse_range,
)


def test_end_col_for_sport_golf_and_other():
    assert end_col_for_sport("GOLF") == "E"
    assert end_col_for_sport("PGAMain") == "E"
    assert end_col_for_sport("NBA") == "H"


def test_ranges_for_sport():
    assert data_range_for_sport("NBA") == "NBA!A2:H"
    assert header_range_for_sport("NBA") == "NBA!A1:H1"
    assert lineup_range_for_sport("NBA") == "NBA!J3:W999"
    assert lineup_range_for_sport("PGAShowdown") == "PGAShowdown!L3:T999"
    assert lineup_range_for_sport("PGAWeekend") == "PGAWeekend!L3:T999"


def test_build_values_for_vip_lineup():
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

    values, format_plan = build_values_for_vip_lineup(user, players)

    assert values[0][:4] == ["VIP", None, "PMR", 1.2]
    assert values[1][:3] == ["Pos", "Name", "Own"]
    assert values[2][1] == "Alpha 🔥"
    assert values[3][1] == "Beta ❄️"
    assert values[-1][0] == "rank"

    # Rows: 0=user, 1=header, 2=Alpha, 3=Beta, 4=footer ("rank"). Salary is
    # column offset 3 (Pos, Name, Own, Salary) in every one of those rows.
    assert format_plan == [
        CellFormat(row=2, col=3, number_format=NumberFormat.CURRENCY),
        CellFormat(row=3, col=3, number_format=NumberFormat.CURRENCY),
        CellFormat(row=4, col=3, number_format=NumberFormat.CURRENCY),
    ]
    assert values[2][3] == 8000
    assert values[3][3] == 7000
    assert values[4][3] == 50000


def test_parse_range():
    assert parse_range("NBA!J3:W999") == RangeOrigin(sheet="NBA", start_col="J", start_row=3, end_col="W")
    assert parse_range("MLB!L8:Z56") == RangeOrigin(sheet="MLB", start_col="L", start_row=8, end_col="Z")
