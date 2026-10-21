"""CompletionProcessor soft-finish: the cash summary, its dedup key and the VIP list.

The announcement is asserted verbatim; the stored dedup key is pinned to a golden
value so a change to what counts as "the same summary" shows up here.
"""

import datetime
import logging

import pytest

from tests.completion_processor_fakes import (
    FixedPresence,
    cashed_row,
    freeze_clock,
    leaderboard,
    make_conn,
    make_sport,
    stored_events,
)
from tests.completion_processor_scenarios import DK_ID, run_soft_finish

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


@pytest.fixture
def conn():
    connection = make_conn()
    yield connection
    connection.close()


def _summary(top, cashing, vips, *, header=HEADER, when="2024-01-01 00:00:00"):
    return "\n".join(
        [header, f"• 🕒 {when}", *TAIL, f"• 🏆 Top score: {top}", f"• 💵 Cashing score: {cashing}"]
        + [f"• ⭐ VIPs cashed (visible rows): {vips}"]
    )


def _board(top, cashing, *rows):
    return leaderboard(
        leader={"timeRemaining": 0, "fantasyPoints": top},
        last_winning={"timeRemaining": 0, "fantasyPoints": cashing},
        rows=list(rows),
    )


def test_soft_finish_announcement_text_and_kind(conn):
    payload = _board(229, 185.5, cashed_row("FooBar"))
    presence = FixedPresence("present")
    sender = run_soft_finish(conn, payload=payload, vips=["FooBar"], presence=presence, **LINKED)
    assert sender.messages == [_summary("229.00", "185.50", "FooBar")]
    [event] = stored_events(conn, DK_ID)
    assert event.startswith("soft_finish:")
    assert presence.calls == [(DK_ID, "2024-01-01 00:00:00", ["FooBar"])]


def test_soft_finish_without_cashed_vips_says_none(conn):
    sender = run_soft_finish(conn, payload=_board(229, 185.5, cashed_row("stranger")), vips=["FooBar"], **LINKED)
    assert sender.messages == [_summary("229.00", "185.50", "none")]


@pytest.mark.parametrize(
    ("top", "cashing", "shown"),
    [(229.005, 185.125, ("229.01", "185.13")), (229, "185.5", ("229.00", "185.50")), (" 7 ", 0.004, ("7.00", "0.00"))],
    ids=["half-up", "int-and-text", "padded-and-tiny"],
)
def test_soft_finish_scores_are_shown_to_the_cent_rounding_half_up(conn, top, cashing, shown):
    sender = run_soft_finish(conn, payload=_board(top, cashing, cashed_row("x")), **LINKED)
    assert sender.messages == [_summary(*shown, "none")]


def test_soft_finish_announcement_shows_time_left_until_the_start(conn, monkeypatch):
    freeze_clock(monkeypatch, datetime.datetime(2023, 12, 31, 23, 35))
    sender = run_soft_finish(conn, **LINKED)
    assert sender.messages == [_summary("229.00", "185.50", "none", when="2024-01-01 00:00:00 (⏳ 25m)")]


def test_soft_finish_dedup_key_is_pinned_to_a_golden_value(conn):
    payload = _board(229, 185.125, *[cashed_row(name) for name in ["Zoë", "ab", "a_x", "Zed", "alice"]])
    vips = ["Zoë", "ab", "a_x", "Zed", "alice"]
    sports = {"NFLShowdown": make_sport("NFLShowdown")}
    run_soft_finish(conn, payload=payload, vips=vips, sport="NFLShowdown", sport_choices=sports)
    # sha256 of {"cashing_score":"185.13","dk_id":42,"sport":"NFLSHOWDOWN","top_score":"229.00",
    # "vips_cashed":["a_x","ab","alice","zed","zo\u00eb"]} (sorted keys, compact, ASCII-escaped).
    assert stored_events(conn, DK_ID) == [
        "soft_finish:5eb1396dd83e57cab6a6599ba08c0e6c17e37b75ff69e1126f377706b3a542dc"
    ]


def test_soft_finish_lists_cashed_vips_sorted_case_insensitively(conn):
    names = ["Zed", "ab", "a_x", "alice"]
    sender = run_soft_finish(conn, payload=_board(229, 185.5, *map(cashed_row, names)), vips=names, **LINKED)
    assert sender.messages == [_summary("229.00", "185.50", "a_x, ab, alice, Zed")]


def test_soft_finish_vip_list_skips_strangers_uncashed_and_nameless_rows_without_stopping(conn):
    rows = [
        cashed_row("stranger"),
        cashed_row("Broke", winning_value=0),
        cashed_row(None),
        cashed_row("One", winning_value=0.01),
        cashed_row(" Zed "),
        cashed_row("zed"),
    ]
    vips = ["Zed", "Broke", "None", "XXXX", "One"]
    sender = run_soft_finish(conn, payload=_board(229, 185.5, *rows), vips=vips, **LINKED)
    assert sender.messages == [_summary("229.00", "185.50", "One, Zed")]


def test_soft_finish_summary_is_resent_as_updated_only_when_it_changes(conn):
    payload = _board(229, 185.5, cashed_row("FooBar"))
    run_soft_finish(conn, payload=payload, vips=["FooBar"], **LINKED)
    same = run_soft_finish(conn, payload=payload, vips=["FooBar"], seed=False, **LINKED)
    moved = run_soft_finish(
        conn, payload=_board(230, 185.5, cashed_row("FooBar")), vips=["FooBar"], seed=False, **LINKED
    )
    assert same.messages == []
    assert moved.messages == [_summary("230.00", "185.50", "FooBar", header=HEADER.replace(":", " (updated):", 1))]
    assert len(stored_events(conn, DK_ID)) == 2


@pytest.mark.parametrize("part", ["leader", "lastWinningEntry"])
def test_soft_finish_ignores_a_leaderboard_part_that_is_not_an_object_without_error(conn, caplog, part):
    payload = leaderboard() | {part: "n/a"}
    with caplog.at_level(logging.WARNING):
        assert run_soft_finish(conn, payload=payload).messages == []
    assert caplog.text == ""
