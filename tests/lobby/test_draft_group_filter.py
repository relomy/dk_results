"""Draft Group Filter rules (`filter_draft_groups`) and Featured draft group selection."""

import datetime

from dk_results.domain.sport import (
    NFLAfternoonSport,
    NFLShowdownSport,
    NFLSport,
    PGAShowdownSport,
    PGAWeekendSport,
    Sport,
    StartWindow,
)
from dk_results.lobby.draft_group_filter import filter_draft_groups, get_featured_draft_group_ids


def test_filter_draft_groups_filters():
    class DummySport(Sport):
        name = "TEST"
        suffixes = (r"\(Main\)",)
        start_windows = (StartWindow(datetime.time(18, 0)),)
        contest_restraint_game_type_id = 99

    response = {
        "DraftGroups": [
            {
                "DraftGroupTag": "Other",
                "ContestStartTimeSuffix": "(Main)",
                "DraftGroupId": 1,
                "StartDateEst": "2024-02-01T12:30:00.000-05:00",
                "ContestTypeId": 1,
                "GameTypeId": 99,
            },
            {
                "DraftGroupTag": "Featured",
                "ContestStartTimeSuffix": None,
                "DraftGroupId": 2,
                "StartDateEst": "2024-02-01T12:30:00.000-05:00",
                "ContestTypeId": 1,
                "GameTypeId": 99,
            },
            {
                "DraftGroupTag": "Featured",
                "ContestStartTimeSuffix": "(Alt)",
                "DraftGroupId": 3,
                "StartDateEst": "2024-02-01T12:30:00.000-05:00",
                "ContestTypeId": 1,
                "GameTypeId": 99,
            },
            {
                "DraftGroupTag": "Featured",
                "ContestStartTimeSuffix": "(Main)",
                "DraftGroupId": 4,
                "StartDateEst": "2024-02-01T12:30:00.000-05:00",
                "ContestTypeId": 1,
                "GameTypeId": 1,
            },
            {
                "DraftGroupTag": "Featured",
                "ContestStartTimeSuffix": "(Main)",
                "DraftGroupId": 5,
                "StartDateEst": "2024-02-01T16:00:00.000-05:00",
                "ContestTypeId": 1,
                "GameTypeId": 99,
            },
            {
                "DraftGroupTag": "Featured",
                "ContestStartTimeSuffix": "(Main)",
                "DraftGroupId": 6,
                "StartDateEst": "2024-02-01T20:00:00.000-05:00",
                "ContestTypeId": 1,
                "GameTypeId": 99,
            },
        ]
    }

    result = filter_draft_groups(response["DraftGroups"], DummySport)
    assert result == [6]


def test_filter_draft_groups_no_restraints_accepts_everything():
    """A sport with no game-type/time/suffix restraints (all default None) passes through."""

    class UnrestrictedSport(Sport):
        name = "UNRESTRICTED_TEST"

    response = {
        "DraftGroups": [
            {
                "DraftGroupTag": "Featured",
                "ContestStartTimeSuffix": None,
                "DraftGroupId": 101,
                "StartDateEst": "2024-02-01T02:00:00.000-05:00",
                "ContestTypeId": 1,
                "GameTypeId": 5,
            },
            {
                "DraftGroupTag": "Featured",
                "ContestStartTimeSuffix": "(Anything)",
                "DraftGroupId": 102,
                "StartDateEst": "2024-02-01T23:00:00.000-05:00",
                "ContestTypeId": 1,
                "GameTypeId": 5,
            },
        ]
    }

    result = filter_draft_groups(response["DraftGroups"], UnrestrictedSport)
    assert result == [101, 102]


def test_filter_draft_groups_skips_non_featured_tag_without_suffix():
    class DummySport(Sport):
        name = "TEST_TAG_SKIP"

    response = {
        "DraftGroups": [
            {
                "DraftGroupTag": "Other",
                "ContestStartTimeSuffix": None,
                "DraftGroupId": 201,
                "StartDateEst": "2024-02-01T12:00:00.000-05:00",
                "ContestTypeId": 1,
                "GameTypeId": 1,
            },
        ]
    }

    result = filter_draft_groups(response["DraftGroups"], DummySport)
    assert result == []


def test_get_featured_draft_group_ids_uses_exact_tag_without_sport_filters():
    groups = [
        {"DraftGroupId": 1, "DraftGroupTag": "Featured"},
        {"DraftGroupId": 2, "DraftGroupTag": "featured"},
        {"DraftGroupId": 3, "DraftGroupTag": " Featured"},
    ]

    assert get_featured_draft_group_ids(groups) == {1}


def test_filter_draft_groups_nfl_showdown():
    response = {
        "DraftGroups": [
            {
                "DraftGroupTag": "Featured",
                "ContestStartTimeSuffix": "(ABC @ DEF)",
                "DraftGroupId": 10,
                "StartDateEst": "2024-02-01T20:00:00.000-05:00",
                "ContestTypeId": 1,
                "GameTypeId": 96,
            },
            {
                "DraftGroupTag": "Featured",
                "ContestStartTimeSuffix": "(ABC @ DEF)",
                "DraftGroupId": 11,
                "StartDateEst": "2024-02-01T20:00:00.000-05:00",
                "ContestTypeId": 1,
                "GameTypeId": 96,
            },
            {
                "DraftGroupTag": "Featured",
                "ContestStartTimeSuffix": "(XYZ @ QRS)",
                "DraftGroupId": 12,
                "StartDateEst": "2024-02-01T21:00:00.000-05:00",
                "ContestTypeId": 1,
                "GameTypeId": 96,
            },
        ]
    }

    result = filter_draft_groups(response["DraftGroups"], NFLShowdownSport)
    assert result == [12]


def _showdown_group(draft_group_id, start, suffix="(DAL @ GB)"):
    return {
        "DraftGroupTag": "Featured",
        "ContestStartTimeSuffix": suffix,
        "DraftGroupId": draft_group_id,
        "StartDateEst": f"2026-10-18T{start}:00.000-04:00",
        "ContestTypeId": 96,
        "GameTypeId": 96,
    }


def test_filter_draft_groups_nfl_showdown_start_boundary_at_18_00():
    groups = [_showdown_group(1, "17:59"), _showdown_group(2, "18:00")]

    assert filter_draft_groups(groups, NFLShowdownSport) == [2]


def test_filter_draft_groups_nfl_showdown_admits_morning_international_game():
    """2026-10-18 lobby: HOU vs JAX in London, draft group 154948, Sun 9:30AM ET."""
    groups = [_showdown_group(154948, "09:30", suffix="(HOU vs JAX)")]

    assert filter_draft_groups(groups, NFLShowdownSport) == [154948]


def test_filter_draft_groups_nfl_showdown_midday_upper_bound_exclusive_at_13_00():
    """12:30 (Thanksgiving) is admitted; 13:00 (Sunday 1:00 PM window) is rejected."""
    groups = [_showdown_group(1, "12:30"), _showdown_group(2, "13:00", suffix="(CHI @ ATL)")]

    assert filter_draft_groups(groups, NFLShowdownSport) == [1]


def test_filter_draft_groups_nfl_showdown_morning_lower_bound_inclusive_at_06_00():
    groups = [_showdown_group(1, "05:59"), _showdown_group(2, "06:00")]

    assert filter_draft_groups(groups, NFLShowdownSport) == [2]


def test_filter_draft_groups_nfl_showdown_rejects_sunday_day_window_featured():
    """2026-10-18 lobby: 13:00 CHI @ ATL (154949) and 16:25 BUF @ LV (154957); 16:05 is the other Sunday window."""
    groups = [
        _showdown_group(154949, "13:00", suffix="(CHI @ ATL)"),
        _showdown_group(154955, "16:05", suffix="(SEA @ LAR)"),
        _showdown_group(154957, "16:25", suffix="(BUF @ LV)"),
    ]

    assert filter_draft_groups(groups, NFLShowdownSport) == []


def test_filter_draft_groups_nfl_showdown_full_2026_10_18_lobby_keeps_morning_and_night_only():
    groups = [
        _showdown_group(154948, "09:30", suffix="(HOU vs JAX)"),
        _showdown_group(154949, "13:00", suffix="(CHI @ ATL)"),
        _showdown_group(154957, "16:25", suffix="(BUF @ LV)"),
        _showdown_group(154959, "20:20", suffix="(DAL @ GB)"),
    ]

    assert filter_draft_groups(groups, NFLShowdownSport) == [154948, 154959]


def test_filter_draft_groups_nfl_showdown_drops_morning_groups_sharing_a_start_minute():
    groups = [
        _showdown_group(1, "09:30", suffix="(HOU vs JAX)"),
        _showdown_group(2, "09:30", suffix="(MIA vs NO)"),
        _showdown_group(3, "20:20"),
    ]

    assert filter_draft_groups(groups, NFLShowdownSport) == [3]


def test_filter_draft_groups_nfl_showdown_drops_night_groups_sharing_a_start_minute():
    """Monday doubleheader shape: two Featured Showdowns at 20:20 are both dropped."""
    groups = [
        _showdown_group(1, "20:20", suffix="(DAL @ GB)"),
        _showdown_group(2, "20:20", suffix="(MIA @ NO)"),
    ]

    assert filter_draft_groups(groups, NFLShowdownSport) == []


def test_filter_draft_groups_sport_without_start_windows_accepts_any_start():
    class OpenSport(Sport):
        name = "TEST"
        contest_restraint_game_type_id = 96

    groups = [_showdown_group(1, "00:05"), _showdown_group(2, "09:30"), _showdown_group(3, "23:59")]

    assert filter_draft_groups(groups, OpenSport) == [1, 2, 3]


def test_filter_draft_groups_nfl_showdown_super_bowl_suffix():
    response = {
        "DraftGroups": [
            {
                "DraftGroupTag": "Featured",
                "ContestStartTimeSuffix": "(Super Bowl LX)",
                "DraftGroupId": 21,
                "StartDateEst": "2026-02-08T18:30:00.000-05:00",
                "ContestTypeId": 1,
                "GameTypeId": 96,
            },
            {
                "DraftGroupTag": "Featured",
                "ContestStartTimeSuffix": "(Super Bowl LX)",
                "DraftGroupId": 22,
                "StartDateEst": "2026-02-08T18:30:00.000-05:00",
                "ContestTypeId": 1,
                "GameTypeId": 192,
            },
        ]
    }

    result = filter_draft_groups(response["DraftGroups"], NFLShowdownSport)
    assert result == [21]


def test_filter_draft_groups_nfl_showdown_excludes_day_window_featured():
    """DK tags one Featured Showdown per Sunday window, not just primetime.

    Live data (2026-09-17) showed Featured Showdown draft groups at 1:00 PM
    and 4:25 PM ET on a normal Sunday alongside the Thursday-night one — only
    the primetime slate should be tracked as NFLShowdown.
    """
    response = {
        "DraftGroups": [
            {
                "DraftGroupTag": "Featured",
                "ContestStartTimeSuffix": "(DET @ BUF)",
                "DraftGroupId": 153434,
                "StartDateEst": "2026-09-17T20:15:00.000-05:00",
                "ContestTypeId": 96,
                "GameTypeId": 96,
            },
            {
                "DraftGroupTag": "Featured",
                "ContestStartTimeSuffix": "(MIN @ CHI)",
                "DraftGroupId": 153436,
                "StartDateEst": "2026-09-20T13:00:00.000-05:00",
                "ContestTypeId": 96,
                "GameTypeId": 96,
            },
            {
                "DraftGroupTag": "Featured",
                "ContestStartTimeSuffix": "(WAS @ DAL)",
                "DraftGroupId": 153446,
                "StartDateEst": "2026-09-20T16:25:00.000-05:00",
                "ContestTypeId": 96,
                "GameTypeId": 96,
            },
        ]
    }

    result = filter_draft_groups(response["DraftGroups"], NFLShowdownSport)
    assert result == [153434]


def test_filter_draft_groups_nfl_classic_excludes_showdown():
    response = {
        "DraftGroups": [
            {
                "DraftGroupTag": "Featured",
                "ContestStartTimeSuffix": None,
                "DraftGroupId": 41,
                "StartDateEst": "2026-09-10T13:00:00.000-05:00",
                "ContestTypeId": 1,
                "GameTypeId": 1,
            },
            {
                "DraftGroupTag": "Featured",
                "ContestStartTimeSuffix": "(ABC @ DEF)",
                "DraftGroupId": 42,
                "StartDateEst": "2026-09-10T13:00:00.000-05:00",
                "ContestTypeId": 1,
                "GameTypeId": 96,
            },
        ]
    }

    result = filter_draft_groups(response["DraftGroups"], NFLSport)
    assert result == [41]


def test_filter_draft_groups_nfl_classic_excludes_suffixed_draft_groups():
    """NFLSport is suffixless-only: real Classic-suffixed groups all get rejected."""

    def _group(draft_group_id, suffix):
        return {
            "DraftGroupTag": "Featured",
            "ContestStartTimeSuffix": suffix,
            "DraftGroupId": draft_group_id,
            "StartDateEst": "2026-09-10T13:00:00.000-05:00",
            "ContestTypeId": 1,
            "GameTypeId": 1,
        }

    response = {
        "DraftGroups": [
            _group(51, None),
            _group(52, "(Afternoon Only)"),
            _group(53, "(Thu-Mon)"),
            _group(54, "(Sun-Mon)"),
            _group(55, "(Early Only)"),
            _group(56, "(Afternoon Turbo)"),
        ]
    }

    result = filter_draft_groups(response["DraftGroups"], NFLSport)
    assert result == [51]


def test_filter_draft_groups_nfl_afternoon_classic_only():
    """NFLAfternoonSport accepts Classic (Afternoon Only) but rejects Tiers/Snake."""
    response = {
        "DraftGroups": [
            {
                "DraftGroupTag": "Featured",
                "ContestStartTimeSuffix": "(Afternoon Only)",
                "DraftGroupId": 61,
                "StartDateEst": "2026-09-10T13:00:00.000-05:00",
                "ContestTypeId": 1,
                "GameTypeId": 1,
            },
            {
                "DraftGroupTag": "Featured",
                "ContestStartTimeSuffix": "(Afternoon Only)",
                "DraftGroupId": 62,
                "StartDateEst": "2026-09-10T13:00:00.000-05:00",
                "ContestTypeId": 51,
                "GameTypeId": 51,
            },
            {
                "DraftGroupTag": "Featured",
                "ContestStartTimeSuffix": "(Afternoon Only)",
                "DraftGroupId": 63,
                "StartDateEst": "2026-09-10T13:00:00.000-05:00",
                "ContestTypeId": 189,
                "GameTypeId": 189,
            },
        ]
    }

    result = filter_draft_groups(response["DraftGroups"], NFLAfternoonSport)
    assert result == [61]


def test_filter_draft_groups_pga_weekend_strict():
    response = {
        "DraftGroups": [
            {
                "DraftGroupTag": "Featured",
                "ContestStartTimeSuffix": "(Weekend PGA TOUR)",
                "DraftGroupId": 31,
                "StartDateEst": "2026-02-08T11:23:00.000-05:00",
                "ContestTypeId": 29,
                "GameTypeId": 33,
            },
            {
                "DraftGroupTag": "Featured",
                "ContestStartTimeSuffix": "(Round 3 PGA TOUR)",
                "DraftGroupId": 32,
                "StartDateEst": "2026-02-08T07:00:00.000-05:00",
                "ContestTypeId": 87,
                "GameTypeId": 87,
            },
        ]
    }

    result = filter_draft_groups(response["DraftGroups"], PGAWeekendSport)
    assert result == [31]


def test_filter_draft_groups_pga_showdown_standard_only():
    response = {
        "DraftGroups": [
            {
                "DraftGroupTag": "Featured",
                "ContestStartTimeSuffix": "(Round 4 TOUR)",
                "DraftGroupId": 41,
                "StartDateEst": "2026-02-09T10:45:00.000-05:00",
                "ContestTypeId": 87,
                "GameTypeId": 87,
            },
            {
                "DraftGroupTag": "Featured",
                "ContestStartTimeSuffix": "(Late Round 4 TOUR)",
                "DraftGroupId": 42,
                "StartDateEst": "2026-02-09T12:24:00.000-05:00",
                "ContestTypeId": 154,
                "GameTypeId": 154,
            },
            {
                "DraftGroupTag": "Featured",
                "ContestStartTimeSuffix": "(Round 4 DP World Tour)",
                "DraftGroupId": 43,
                "StartDateEst": "2026-02-09T10:45:00.000-05:00",
                "ContestTypeId": 87,
                "GameTypeId": 87,
            },
        ]
    }

    result = filter_draft_groups(response["DraftGroups"], PGAShowdownSport)
    assert result == [41]


def test_get_draft_groups_allows_suffixless():
    class DummySport(Sport):
        name = "TEST"

    response = {
        "DraftGroups": [
            {
                "DraftGroupTag": "Featured",
                "ContestStartTimeSuffix": None,
                "DraftGroupId": 1,
                "StartDateEst": "2024-02-01T12:30:00.000-05:00",
                "ContestTypeId": 1,
                "GameTypeId": 1,
            }
        ]
    }
    assert filter_draft_groups(response["DraftGroups"], DummySport) == [1]
