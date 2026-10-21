"""The exact Discord text and stored record of each CompletionProcessor milestone.

Every announcement is asserted verbatim (sport emoji, names, dates, DK id, links),
alongside the notification kind it records and the presence query it makes.
"""

import datetime

import pytest

from dk_results.notifications.vip_presence import VIP_PRESENT
from tests.completion_processor_fakes import FixedPresence, freeze_clock, make_conn, stored_events
from tests.completion_processor_scenarios import (
    DK_ID,
    FAR_START,
    STARTED,
    run_completed,
    run_live,
    run_warning,
)

LINKED = {
    "sport_emoji": {"NBA": "🔥"},
    "spreadsheet_id": "sheet1",
    "sheet_gid_map": {"NBA": 7},
    "dashboard_base_url": "https://dash.example/",
    "vips": ["FooBar"],
}
DK_LINE = "• 🔗 DK: [42](<https://www.draftkings.com/contest/gamecenter/42#/>)"
LINK_LINE = (
    "• 📈 Dashboard: [NBA](<https://dash.example/live/nba>)"
    " | 📊 Sheet: [NBA](<https://docs.google.com/spreadsheets/d/sheet1/edit#gid=7>)"
)


def _text(prefix, when):
    return "\n".join([f"{prefix}: 🔥 NBA — Main Slate", f"• 🕒 {when}", DK_LINE, LINK_LINE])


@pytest.fixture
def conn():
    connection = make_conn()
    yield connection
    connection.close()


def test_warning_announcement_text_kind_and_presence_query(conn, monkeypatch):
    presence = FixedPresence(VIP_PRESENT)
    sender = run_warning(conn, monkeypatch, presence=presence, **LINKED)
    assert sender.messages == [_text("Contest starting soon (25m)", f"{FAR_START} (⏳ 25m)")]
    assert stored_events(conn, DK_ID) == ["warning:25"]
    assert presence.calls == [(DK_ID, FAR_START, ["FooBar"])]


def test_live_announcement_text_kind_and_presence_query(conn):
    presence = FixedPresence(VIP_PRESENT)
    sender = run_live(conn, presence=presence, **LINKED)
    assert sender.messages == [_text("Contest started", STARTED)]
    assert stored_events(conn, DK_ID) == ["live"]
    assert presence.calls[0] == (DK_ID, STARTED, ["FooBar"])


def test_completed_announcement_text_kind_and_presence_query(conn):
    presence = FixedPresence("unknown")
    sender = run_completed(conn, presence=presence, **LINKED)
    assert sender.messages == [_text("Contest ended", STARTED)]
    assert stored_events(conn, DK_ID) == ["live", "completed"]
    assert presence.calls == [(DK_ID, STARTED, ["FooBar"])]


def test_announcement_without_sheet_or_dashboard_says_sheet_is_unavailable(conn):
    sender = run_live(conn)
    assert sender.messages == [
        "\n".join(
            [
                "Contest started: 🏀 NBA — Main Slate",
                f"• 🕒 {STARTED}",
                DK_LINE,
                "• 📊 Sheet: n/a",
            ]
        )
    ]


@pytest.mark.parametrize(
    ("start", "now", "shown"),
    [
        ("2024-01-01 12:00:00", datetime.datetime(2024, 1, 1, 10, 30), "1h30m"),
        ("2024-01-01 12:00:00", datetime.datetime(2024, 1, 1, 11, 59, 59), "1s"),
        ("2024-01-01 12:00:00", datetime.datetime(2024, 1, 1, 12, 0, 0), None),
        ("2024-01-01 12:00:00", datetime.datetime(2024, 1, 1, 12, 0, 1), None),
        (
            "2024-01-01T12:00:00+00:00",
            datetime.datetime(2024, 1, 1, 10, 30, tzinfo=datetime.timezone.utc),
            "1h30m",
        ),
    ],
    ids=["hours-and-minutes", "one-second-left", "starts-now", "already-started", "timezone-aware"],
)
def test_live_announcement_shows_time_left_only_while_the_start_is_ahead(conn, monkeypatch, start, now, shown):
    freeze_clock(monkeypatch, now)
    sender = run_live(conn, start=start)
    suffix = f" (⏳ {shown})" if shown else ""
    assert sender.messages[0].splitlines()[1] == f"• 🕒 {start}{suffix}"
