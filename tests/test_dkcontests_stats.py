"""dkcontests lobby breakdown: per-date and per-start-time double-up stats."""

import datetime

import dk_results.cli.dkcontests as dkcontests
from dk_results.domain.contest import Contest
from tests.dkcontests_payloads import _contest_payload


def test_print_stats_includes_largest_entry_count(capsys):
    contests = [
        Contest.from_lobby(_contest_payload(1, entries=150, fee=25), "NFL"),
        Contest.from_lobby(_contest_payload(2, entries=230, fee=25), "NFL"),
    ]

    dkcontests.print_stats(contests)

    out = capsys.readouterr().out
    assert "Breakdown per date:" in out
    assert "$25:   2 contest(s) (largest entry count:  230)" in out


def test_build_contest_stats_groups_contests_by_start_time():
    contests = [
        Contest.from_lobby(
            _contest_payload(1, entries=150, fee=25, start_dt=datetime.datetime(2023, 11, 14, 19)),
            "NFL",
        ),
        Contest.from_lobby(
            _contest_payload(2, entries=300, fee=25, start_dt=datetime.datetime(2023, 11, 14, 13)),
            "NFL",
        ),
        Contest.from_lobby(
            _contest_payload(3, entries=100, fee=10, start_dt=datetime.datetime(2023, 11, 14, 13)),
            "NFL",
        ),
    ]

    stats = dkcontests.build_contest_stats(contests, include_largest=True)

    assert stats == {
        "2023-11-14": {
            "count": 3,
            "dubs": {
                10: {"count": 1, "largest": 100},
                25: {"count": 2, "largest": 300},
            },
            "by_start_time": {
                "13:00": {
                    "count": 2,
                    "dubs": {
                        10: {"count": 1, "largest": 100},
                        25: {"count": 1, "largest": 300},
                    },
                },
                "19:00": {
                    "count": 1,
                    "dubs": {25: {"count": 1, "largest": 150}},
                },
            },
        }
    }


def test_build_contest_stats_counts_double_ups_without_largest_entries():
    contests = [
        Contest.from_lobby(_contest_payload(1, fee=10, start_dt=datetime.datetime(2023, 11, 14, 13)), "NFL"),
        Contest.from_lobby(_contest_payload(2, fee=10, start_dt=datetime.datetime(2023, 11, 14, 13)), "NFL"),
        Contest.from_lobby(_contest_payload(3, fee=25, start_dt=datetime.datetime(2023, 11, 14, 19)), "NFL"),
    ]

    stats = dkcontests.build_contest_stats(contests)

    assert stats["2023-11-14"]["dubs"] == {10: 2, 25: 1}
    assert stats["2023-11-14"]["by_start_time"]["13:00"]["dubs"] == {10: 2}
    assert stats["2023-11-14"]["by_start_time"]["19:00"]["dubs"] == {25: 1}


def test_build_contest_stats_combines_contests_in_the_same_displayed_minute():
    contests = [
        Contest.from_lobby(_contest_payload(1, start_dt=datetime.datetime(2023, 11, 14, 19, 0)), "NFL"),
        Contest.from_lobby(_contest_payload(2, start_dt=datetime.datetime(2023, 11, 14, 19, 0, 45)), "NFL"),
    ]

    stats = dkcontests.build_contest_stats(contests)

    assert stats["2023-11-14"]["by_start_time"] == {"19:00": {"count": 2, "dubs": {25: 2}}}


def test_print_stats_breaks_dates_down_by_sorted_start_time(capsys):
    contests = [
        Contest.from_lobby(
            _contest_payload(1, entries=150, fee=25, start_dt=datetime.datetime(2023, 11, 14, 19)),
            "NFL",
        ),
        Contest.from_lobby(
            _contest_payload(2, entries=300, fee=25, start_dt=datetime.datetime(2023, 11, 14, 13)),
            "NFL",
        ),
        Contest.from_lobby(
            _contest_payload(3, entries=100, fee=10, start_dt=datetime.datetime(2023, 11, 14, 13)),
            "NFL",
        ),
    ]

    dkcontests.print_stats(contests)

    assert capsys.readouterr().out.splitlines() == [
        "Breakdown per date:",
        "2023-11-14 -   3 total contests",
        "  13:00 -   2 total contests",
        "    Single-entry double ups:",
        "           $10:   1 contest(s) (largest entry count:  100)",
        "           $25:   1 contest(s) (largest entry count:  300)",
        "  19:00 -   1 total contests",
        "    Single-entry double ups:",
        "           $25:   1 contest(s) (largest entry count:  150)",
    ]


def test_print_stats_marks_featured_and_selected_buckets_independently(capsys):
    featured = Contest.from_lobby(
        {**_contest_payload(1, start_dt=datetime.datetime(2023, 11, 14, 13)), "dg": 101}, "NFL"
    )
    selected = Contest.from_lobby(
        {**_contest_payload(2, start_dt=datetime.datetime(2023, 11, 14, 19)), "dg": 202}, "NFL"
    )

    dkcontests.print_stats(
        [featured, selected],
        featured_draft_group_ids={101},
        selected_contest=selected,
    )

    lines = capsys.readouterr().out.splitlines()
    assert "  13:00 [feat] -   1 total contests" in lines
    assert "  19:00 -   1 total contests [*]" in lines


def test_print_stats_marks_a_mixed_featured_bucket_once(capsys):
    contests = [
        Contest.from_lobby({**_contest_payload(1, start_dt=datetime.datetime(2023, 11, 14, 13, 10)), "dg": 101}, "NFL"),
        Contest.from_lobby(
            {**_contest_payload(2, start_dt=datetime.datetime(2023, 11, 14, 13, 10, 45)), "dg": 202}, "NFL"
        ),
    ]

    dkcontests.print_stats(contests, featured_draft_group_ids={101, 303})

    assert capsys.readouterr().out.splitlines().count("  13:10 [feat] -   2 total contests") == 1


def test_print_stats_omits_featured_marker_without_metadata(capsys):
    contest = Contest.from_lobby(_contest_payload(1), "NFL")

    dkcontests.print_stats([contest])

    assert "[feat]" not in capsys.readouterr().out


def test_print_stats_includes_active_scope(capsys):
    dkcontests.print_stats([], scope="date=2023-11-14, time=13:10, fee=$25, query=any")

    assert capsys.readouterr().out.splitlines() == ["Scope: date=2023-11-14, time=13:10, fee=$25, query=any"]


def test_print_selected_contest_shows_selection_details(capsys):
    contest = Contest.from_lobby(
        {**_contest_payload(7, entries=230, fee=25, start_dt=datetime.datetime(2023, 11, 14, 13)), "dg": 701},
        "NFL",
    )

    dkcontests._print_selected_contest(contest)

    assert capsys.readouterr().out.splitlines() == [
        "Selected contest:",
        "  ID: 7",
        "  Name: Contest 7",
        "  Fee: $25",
        "  Start time: 2023-11-14 13:00",
        "  Draft group: 701",
        "  Entry count: 230",
        "  Reason: largest matching $25 double-up",
    ]


def test_filter_contests_by_start_time_uses_displayed_minute():
    contests = [
        Contest.from_lobby(_contest_payload(1, start_dt=datetime.datetime(2023, 11, 14, 13, 10)), "NFL"),
        Contest.from_lobby(_contest_payload(2, start_dt=datetime.datetime(2023, 11, 14, 13, 10, 45)), "NFL"),
        Contest.from_lobby(_contest_payload(3, start_dt=datetime.datetime(2023, 11, 14, 14, 10)), "NFL"),
    ]

    filtered = dkcontests._filter_contests_by_start_time(contests, datetime.time(13, 10))

    assert [contest.id for contest in filtered] == [1, 2]


def test_print_stats_sorts_dates_chronologically(capsys):
    contests = [
        Contest.from_lobby(_contest_payload(1, start_dt=datetime.datetime(2023, 11, 15, 19)), "NFL"),
        Contest.from_lobby(_contest_payload(2, start_dt=datetime.datetime(2023, 11, 14, 13)), "NFL"),
    ]

    dkcontests.print_stats(contests)

    lines = capsys.readouterr().out.splitlines()
    assert lines.index("2023-11-14 -   1 total contests") < lines.index("2023-11-15 -   1 total contests")
