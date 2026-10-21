"""CompletionProcessor soft-finish: the cash summary, its dedup key and the VIP list.

The announcement is asserted verbatim; the stored dedup key is pinned to a golden
value so a change to what counts as "the same summary" shows up here.
"""

import datetime
import json
import logging
from pathlib import Path

import pytest

LINKED = {
    "sport_emoji": {"NBA": "🔥"},
    "spreadsheet_id": "sheet1",
    "sheet_gid_map": {"NBA": 7},
    "dashboard_base_url": "https://dash.example/",
}
HEADER = "Contest soft-finished: 🔥 NBA — Main Slate"
TAIL = [
    "• 🔗 DK: [42](<https://www.draftkings.com/contest/gamecenter/42#/>)",
    "• 📈 Dashboard: [NBA](<https://dash.example/live/nba>)"
    " | 📊 Sheet: [NBA](<https://docs.google.com/spreadsheets/d/sheet1/edit#gid=7>)",
]


REAL_LEADERBOARD = Path(__file__).parents[1] / "draftkings" / "data" / "leaderboard_194664936.json"


def _summary(top, cashing, vips, *, header=HEADER, when="2024-01-01 00:00:00", tail=TAIL):
    return "\n".join(
        [header, f"• 🕒 {when}", *tail, f"• 🏆 Top score: {top}", f"• 💵 Cashing score: {cashing}"]
        + [f"• ⭐ VIPs cashed (visible rows): {vips}"]
    )


@pytest.fixture
def board(leaderboard):
    def build(top, cashing, *rows):
        return leaderboard(
            leader={"timeRemaining": 0, "fantasyPoints": top},
            last_winning={"timeRemaining": 0, "fantasyPoints": cashing},
            rows=list(rows) or None,
        )

    return build


def test_soft_finish_announcement_text_and_kind(
    run_soft_finish, board, cashed_row, make_presence, scenario, stored_events
):
    payload = board(229, 185.5, cashed_row("FooBar"))
    presence = make_presence("present")
    sender = run_soft_finish(payload=payload, vips=["FooBar"], presence=presence, **LINKED)
    assert sender.messages == [_summary("229.00", "185.50", "FooBar")]
    [event] = stored_events(scenario.dk_id)
    assert event.startswith("soft_finish:")
    assert presence.calls == [(scenario.dk_id, "2024-01-01 00:00:00", ["FooBar"])]


def test_soft_finish_without_cashed_vips_says_none(run_soft_finish, board, cashed_row):
    sender = run_soft_finish(payload=board(229, 185.5, cashed_row("stranger")), vips=["FooBar"], **LINKED)
    assert sender.messages == [_summary("229.00", "185.50", "none")]


@pytest.mark.parametrize(
    ("top", "cashing", "shown"),
    [(229.005, 185.125, ("229.01", "185.13")), (229, "185.5", ("229.00", "185.50")), (" 7 ", 0.004, ("7.00", "0.00"))],
    ids=["half-up", "int-and-text", "padded-and-tiny"],
)
def test_soft_finish_scores_are_shown_to_the_cent_rounding_half_up(
    run_soft_finish, board, cashed_row, top, cashing, shown
):
    sender = run_soft_finish(payload=board(top, cashing, cashed_row("x")), **LINKED)
    assert sender.messages == [_summary(*shown, "none")]


def test_soft_finish_announcement_shows_time_left_until_the_start(run_soft_finish):
    sender = run_soft_finish(at=datetime.datetime(2023, 12, 31, 23, 35), **LINKED)
    assert sender.messages == [_summary("229.00", "185.50", "none", when="2024-01-01 00:00:00 (⏳ 25m)")]


def test_soft_finish_dedup_key_is_pinned_to_a_golden_value(
    run_soft_finish, board, cashed_row, make_sport, scenario, stored_events
):
    payload = board(229, 185.125, *[cashed_row(name) for name in ["Zoë", "ab", "a_x", "Zed", "alice"]])
    vips = ["Zoë", "ab", "a_x", "Zed", "alice"]
    sports = {"NFLShowdown": make_sport("NFLShowdown")}
    run_soft_finish(payload=payload, vips=vips, sport="NFLShowdown", sport_choices=sports)
    # sha256 of {"cashing_score":"185.13","dk_id":42,"sport":"NFLSHOWDOWN","top_score":"229.00",
    # "vips_cashed":["a_x","ab","alice","zed","zo\u00eb"]} (sorted keys, compact, ASCII-escaped).
    assert stored_events(scenario.dk_id) == [
        "soft_finish:5eb1396dd83e57cab6a6599ba08c0e6c17e37b75ff69e1126f377706b3a542dc"
    ]


def test_soft_finish_lists_cashed_vips_sorted_case_insensitively(run_soft_finish, board, cashed_row):
    names = ["Zed", "ab", "a_x", "alice"]
    sender = run_soft_finish(payload=board(229, 185.5, *map(cashed_row, names)), vips=names, **LINKED)
    assert sender.messages == [_summary("229.00", "185.50", "a_x, ab, alice, Zed")]


def test_soft_finish_vip_list_skips_strangers_uncashed_and_nameless_rows_without_stopping(
    run_soft_finish, board, cashed_row
):
    rows = [
        cashed_row("stranger"),
        cashed_row("Broke", winning_value=0),
        cashed_row(None),
        cashed_row("One", winning_value=0.01),
        cashed_row(" Zed "),
        cashed_row("zed"),
    ]
    vips = ["Zed", "Broke", "None", "XXXX", "One"]
    sender = run_soft_finish(payload=board(229, 185.5, *rows), vips=vips, **LINKED)
    assert sender.messages == [_summary("229.00", "185.50", "One, Zed")]


def test_soft_finish_summary_is_resent_as_updated_only_when_it_changes(
    run_soft_finish, board, cashed_row, scenario, stored_events
):
    payload = board(229, 185.5, cashed_row("FooBar"))
    run_soft_finish(payload=payload, vips=["FooBar"], **LINKED)
    same = run_soft_finish(payload=payload, vips=["FooBar"], seed=False, **LINKED)
    moved = run_soft_finish(payload=board(230, 185.5, cashed_row("FooBar")), vips=["FooBar"], seed=False, **LINKED)
    assert same.messages == []
    assert moved.messages == [_summary("230.00", "185.50", "FooBar", header=HEADER.replace(":", " (updated):", 1))]
    assert len(stored_events(scenario.dk_id)) == 2


@pytest.mark.parametrize("part", ["leader", "lastWinningEntry"])
def test_soft_finish_ignores_a_leaderboard_part_that_is_not_an_object_without_error(
    run_soft_finish, leaderboard, caplog, part
):
    payload = leaderboard() | {part: "n/a"}
    with caplog.at_level(logging.WARNING):
        assert run_soft_finish(payload=payload).messages == []
    assert caplog.text == ""


def _bare_summary(name, top, cashing, vips, *, updated=False):
    header = f"Contest soft-finished{' (updated)' if updated else ''}: 🏀 NBA — {name}"
    dk_line = "• 🔗 DK: [1](<https://www.draftkings.com/contest/gamecenter/1#/>)"
    return _summary(top, cashing, vips, header=header, tail=[dk_line, "• 📊 Sheet: n/a"])


def test_soft_finish_summary_announced_once_then_silent(
    conn, sender, insert_contest, detail, leaderboard, make_results, make_presence, make_processor
):
    insert_contest(name="Live Contest", status="LIVE")
    results = make_results(detail=detail(status="LIVE"), leaderboard=leaderboard())
    processor = make_processor(results=results, sender=sender, presence=make_presence("unknown"))

    processor.run(conn)
    processor.run(conn)

    assert sender.messages == [_bare_summary("Live Contest", "229.00", "185.50", "none")]


def test_soft_finish_names_only_the_vips_who_cashed_in_the_real_leaderboard(
    conn, sender, insert_contest, detail, make_results, make_presence, make_processor
):
    payload = json.loads(REAL_LEADERBOARD.read_text())
    paid_vip, unpaid_vip = (
        next(row["userName"] for row in payload["leaderBoard"] if row["winningValue"] == value) for value in (10, 0)
    )
    insert_contest(name="Live Contest", status="LIVE")
    processor = make_processor(
        results=make_results(detail=detail(status="LIVE"), leaderboard=payload),
        sender=sender,
        presence=make_presence("unknown"),
        vips=[paid_vip, unpaid_vip],
    )

    processor.run(conn)

    (soft,) = [m for m in sender.messages if "soft-finished" in m]
    assert soft.endswith(f"VIPs cashed (visible rows): {paid_vip}")
    assert unpaid_vip not in soft


def test_soft_finish_does_not_count_a_non_cash_payout_type_as_cashed(run_soft_finish, board):
    ticket_only = {
        "userName": "FooBar",
        "timeRemaining": 0,
        "fantasyPoints": 229,
        "winnings": [{"payoutType": "TICKET", "description": "cash", "value": 5}],
    }
    sender = run_soft_finish(payload=board(229, 185.5, ticket_only), vips=["FooBar"], **LINKED)
    assert sender.messages == [_summary("229.00", "185.50", "none")]


def test_soft_finish_resends_updated_when_summary_changes(
    conn, sender, insert_contest, detail, board, make_results, make_presence, make_processor
):
    insert_contest(name="Live Contest", status="LIVE")
    results = make_results(
        detail=detail(status="LIVE"),
        leaderboard=[board(221.5, 180.25), board(223.0, 181.0)],
    )
    processor = make_processor(results=results, sender=sender, presence=make_presence("unknown"))

    processor.run(conn)
    processor.run(conn)

    assert sender.messages == [
        _bare_summary("Live Contest", "221.50", "180.25", "none"),
        _bare_summary("Live Contest", "223.00", "181.00", "none", updated=True),
    ]


def test_soft_finish_summary_is_not_resent_for_equivalent_numbers_and_vip_spelling(
    run_soft_finish, board, cashed_row, scenario, stored_events
):
    first = run_soft_finish(payload=board(123, 99, cashed_row("FooBar")), vips=["FooBar"])
    again = run_soft_finish(payload=board(123.00, 99.0, cashed_row("foobar")), vips=["FooBar"], seed=False)
    assert len(first.messages) == 1
    assert again.messages == []
    assert len(stored_events(scenario.dk_id)) == 1


def test_soft_finish_lists_a_vip_once_when_the_leaderboard_repeats_the_name(run_soft_finish, board, cashed_row):
    rows = [cashed_row("FooBar"), cashed_row("foobar")]
    sender = run_soft_finish(payload=board(229, 185.5, *rows), vips=["FooBar"], **LINKED)
    assert sender.messages == [_summary("229.00", "185.50", "FooBar")]


def test_soft_finish_lists_each_vip_once_in_alphabetical_order(run_soft_finish, board, cashed_row):
    rows = [cashed_row("FooBar"), cashed_row("foobar"), cashed_row("Alpha")]
    sender = run_soft_finish(payload=board(229, 185.5, *rows), vips=["FooBar", "foobar", "Alpha"], **LINKED)
    assert sender.messages == [_summary("229.00", "185.50", "Alpha, FooBar")]


def test_soft_finish_targets_the_live_contest_matching_the_sports_fee_and_keyword(
    insert_contest, run_sync, detail, leaderboard, make_results, make_sport
):
    insert_contest(dk_id=1, draft_group=1, name="Main A", entry_fee=50, status="LIVE", positions_paid=10)
    insert_contest(dk_id=2, draft_group=2, name="Other", entry_fee=100, status="LIVE", positions_paid=10)
    results = make_results(detail=detail(status="LIVE"), leaderboard=leaderboard())
    messages = run_sync(results=results, sport_choices={"NBA": make_sport("NBA", fee=50, keyword="%Main%")})
    assert [m.splitlines()[0] for m in messages] == ["Contest soft-finished: 🏀 NBA — Main A"]
