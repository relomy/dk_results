"""Builder-level tests for the shared Discord announcement chrome.

Asserts exact output text per kind — the single place formatted layout is
verified, so call-site tests don't have to re-assert full formatting.
"""

from dk_results.discord_announcements import (
    DISCORD_ROLE_MAP,
    build_bonus_achievement_announcement,
    build_double_up_found_announcement,
    build_milestone_announcement,
    build_soft_finish_announcement,
    relative_time_from_seconds,
    sheet_link,
    sport_emoji,
)
from dk_results.domain.contest import Contest


def _contest_payload(dk_id: int, *, entry_fee=10, entries=200):
    return {
        "sd": "1700000000000",
        "n": "Test Contest",
        "id": dk_id,
        "dg": 10,
        "po": 0,
        "m": entries,
        "a": entry_fee,
        "ec": 0,
        "mec": 1,
        "attr": {"IsDoubleUp": True, "IsGuaranteed": True},
        "gameType": "Classic",
        "gameTypeId": 1,
    }


def test_sport_emoji_default_and_override():
    assert sport_emoji("UNKNOWN") == "🏟️"
    assert sport_emoji("NBA") == "🏀"
    assert sport_emoji("NBA", {"NBA": "🎯"}) == "🎯"
    assert sport_emoji("OTHER", {"NBA": "🎯"}) == "🏟️"


def test_relative_time_from_seconds_formats_compact_duration():
    assert relative_time_from_seconds(5) == "5s"
    assert relative_time_from_seconds(13 * 60) == "13m"
    assert relative_time_from_seconds(90061) == "1d1h1m"


def test_sheet_link_requires_spreadsheet_id_and_gid():
    assert sheet_link(None, {"NBA": 1}, "NBA") is None
    assert sheet_link("sheet-id", {}, "NBA") is None
    assert sheet_link("sheet-id", {"NBA": 123}, "NBA") == (
        "<https://docs.google.com/spreadsheets/d/sheet-id/edit#gid=123>"
    )


def test_build_milestone_announcement_full_chrome():
    msg = build_milestone_announcement(
        prefix="Contest started",
        sport_name="NBA",
        contest_name="Test Contest",
        start_date="2026-01-01 00:00:00",
        dk_id=123,
        relative_time="13m",
        sheet_link_url="<https://docs.google.com/spreadsheets/d/sheet/edit#gid=1>",
    )
    assert msg == (
        "Contest started: 🏀 NBA — Test Contest\n"
        "• 🕒 2026-01-01 00:00:00 (⏳ 13m)\n"
        "• 🔗 DK: [123](<https://www.draftkings.com/contest/gamecenter/123#/>)\n"
        "• 📊 Sheet: [NBA](<https://docs.google.com/spreadsheets/d/sheet/edit#gid=1>)"
    )


def test_build_milestone_announcement_no_relative_time_or_sheet_link():
    msg = build_milestone_announcement(
        prefix="Contest ended",
        sport_name="UNKNOWN",
        contest_name="Test Contest",
        start_date="2026-01-01 00:00:00",
        dk_id=1,
    )
    assert msg == (
        "Contest ended: 🏟️ UNKNOWN — Test Contest\n"
        "• 🕒 2026-01-01 00:00:00\n"
        "• 🔗 DK: [1](<https://www.draftkings.com/contest/gamecenter/1#/>)\n"
        "• 📊 Sheet: n/a"
    )


def test_build_soft_finish_announcement_appends_cash_summary():
    msg = build_soft_finish_announcement(
        sport_name="NBA",
        contest_name="Test Contest",
        start_date="2026-01-01 00:00:00",
        dk_id=1,
        top_score="229.00",
        cashing_score="185.50",
        vips_cashed=["FooBar"],
    )
    assert msg.startswith("Contest soft-finished: 🏀 NBA — Test Contest\n")
    assert "• 🏆 Top score: 229.00" in msg
    assert "• 💵 Cashing score: 185.50" in msg
    assert "• ⭐ VIPs cashed (visible rows): FooBar" in msg


def test_build_soft_finish_announcement_update_marker_and_no_vips():
    msg = build_soft_finish_announcement(
        sport_name="NBA",
        contest_name="Test Contest",
        start_date="2026-01-01 00:00:00",
        dk_id=1,
        top_score="229.00",
        cashing_score="185.50",
        vips_cashed=[],
        is_update=True,
    )
    assert msg.startswith("Contest soft-finished (updated): ")
    assert "VIPs cashed (visible rows): none" in msg


def test_build_bonus_achievement_announcement_has_no_sheet_link_or_entry_fee():
    msg = build_bonus_achievement_announcement("GOLF", "Rory McIlroy (34.7%) recorded an eagle (+8 pts) (VIPs: zeta)")
    assert msg == "⛳ GOLF — Rory McIlroy (34.7%) recorded an eagle (+8 pts) (VIPs: zeta)"
    assert "Sheet" not in msg
    assert "Entry" not in msg


def test_build_double_up_found_announcement_mapped_sport():
    contest = Contest.from_lobby(_contest_payload(1, entry_fee=5, entries=125), "NBA")
    msg = build_double_up_found_announcement("NBA", [contest])
    # The date bullet is derived from the same fixture, matching Contest.start_dt's
    # own (independently tested) conversion, so this stays an exact-output
    # assertion of the announcement assembly without hardcoding a timezone-
    # dependent literal.
    expected_date = f"{contest.start_dt:%Y-%m-%d}"
    assert msg == (
        ":basketball: New double-up found: 🏀 NBA — Test Contest\n"
        f"• 🕒 {expected_date}\n"
        "• 💰 Entry: 5 | Entries: 125\n"
        "• 🔗 DK: [1](<https://www.draftkings.com/contest/gamecenter/1#/>) "
        "<@&1034206287153594470>"
    )


def test_build_double_up_found_announcement_joins_multiple_contests():
    contests = [
        Contest.from_lobby(_contest_payload(1), "NBA"),
        Contest.from_lobby(_contest_payload(2), "NBA"),
    ]
    msg = build_double_up_found_announcement("NBA", contests)
    assert msg is not None
    assert msg.count("New double-up found") == 2
    assert "\n\n" in msg


def test_build_double_up_found_announcement_gates_unmapped_sport():
    contest = Contest.from_lobby(_contest_payload(1), "MLB")
    assert build_double_up_found_announcement("MLB", [contest]) is None


def test_build_double_up_found_announcement_no_contests():
    assert build_double_up_found_announcement("NBA", []) is None


def test_discord_role_map_unchanged():
    assert DISCORD_ROLE_MAP == {
        "NBA": (":basketball:", "<@&1034206287153594470>"),
        "CFB": (":football:", "<@&1034214536544268439>"),
        "GOLF": (":golf:", "<@&1040014001452630046>"),
        "NFLShowdown": ("<:stonks:858081117876518964>", "<@&1312478274085191770>"),
    }
