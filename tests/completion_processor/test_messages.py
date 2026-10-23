"""The exact Discord text and stored record of each CompletionProcessor milestone.

Every announcement is asserted verbatim (sport emoji, names, dates, DK id, links),
alongside the notification kind it records and the presence query it makes.
"""

import datetime

import pytest

from dk_results.completion_processor.messages import relative_time
from dk_results.notifications.vip_presence import VIP_PRESENT

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


def test_warning_announcement_text_kind_and_presence_query(run_warning, make_presence, scenario, stored_events):
    presence = make_presence(VIP_PRESENT)
    sender = run_warning(presence=presence, **LINKED)
    assert sender.messages == [_text("Contest starting soon (25m)", f"{scenario.far_start} (⏳ 25m)")]
    assert stored_events(scenario.dk_id) == ["warning:25"]
    assert presence.calls == [(scenario.dk_id, scenario.far_start, ["FooBar"])]


def test_live_announcement_text_kind_and_presence_query(run_live, make_presence, scenario, stored_events):
    presence = make_presence(VIP_PRESENT)
    sender = run_live(presence=presence, **LINKED)
    assert sender.messages == [_text("Contest started", scenario.started)]
    assert stored_events(scenario.dk_id) == ["live"]
    assert presence.calls[0] == (scenario.dk_id, scenario.started, ["FooBar"])


def test_completed_announcement_text_kind_and_presence_query(run_completed, make_presence, scenario, stored_events):
    presence = make_presence("unknown")
    sender = run_completed(presence=presence, **LINKED)
    assert sender.messages == [_text("Contest ended", scenario.started)]
    assert stored_events(scenario.dk_id) == ["live", "completed"]
    assert presence.calls == [(scenario.dk_id, scenario.started, ["FooBar"])]


def test_announcement_without_sheet_or_dashboard_says_sheet_is_unavailable(run_live, scenario, bare_text):
    sender = run_live()
    assert sender.messages == [
        bare_text("Contest started", name=scenario.name, dk_id=scenario.dk_id, when=scenario.started)
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
def test_live_announcement_shows_time_left_only_while_the_start_is_ahead(run_live, start, now, shown):
    sender = run_live(start=start, at=now)
    suffix = f" (⏳ {shown})" if shown else ""
    assert sender.messages[0].splitlines()[1] == f"• 🕒 {start}{suffix}"


def test_live_announcement_with_an_unparseable_start_date_omits_the_relative_time(
    run_live, make_presence, scenario, bare_text
):
    # Sorts before any real timestamp, so the DB still treats the contest as started.
    sender = run_live(start="1999-xx", presence=make_presence(VIP_PRESENT))
    assert sender.messages == [bare_text("Contest started", name=scenario.name, dk_id=scenario.dk_id, when="1999-xx")]


def test_warning_shows_whole_minutes_left_and_links_the_sheet_and_dashboard(run_warning, scenario):
    start = datetime.datetime.fromisoformat(scenario.far_start)
    sender = run_warning(
        at=start - datetime.timedelta(minutes=13, seconds=30),
        spreadsheet_id="test-sheet",
        sheet_gid_map={"NBA": 123},
        dashboard_base_url="https://dashboard.example",
    )
    assert sender.messages == [
        "\n".join(
            [
                "Contest starting soon (25m): 🏀 NBA — Main Slate",
                f"• 🕒 {scenario.far_start} (⏳ 13m)",
                DK_LINE,
                "• 📈 Dashboard: [NBA](<https://dashboard.example/live/nba>)"
                " | 📊 Sheet: [NBA](<https://docs.google.com/spreadsheets/d/test-sheet/edit#gid=123>)",
            ]
        )
    ]


def test_announcement_for_a_sport_without_an_emoji_uses_the_default_marker(run_live, scenario, bare_text):
    sender = run_live(sport_emoji={})
    expected = bare_text("Contest started", name=scenario.name, dk_id=scenario.dk_id, when=scenario.started)
    assert sender.messages == [expected.replace("🏀", "🏟️")]


def test_time_left_is_read_from_a_datetime_or_an_iso_string_and_absent_for_anything_else(clock_at):
    start = datetime.datetime(2026, 1, 1, 12, 0, 0)
    now = clock_at(start - datetime.timedelta(minutes=90))
    assert relative_time(start, now) == "1h30m"
    assert relative_time("2026-01-01 12:00:00", now) == "1h30m"
    assert relative_time("bad-date", now) is None
    assert relative_time(None, now) is None
