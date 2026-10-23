"""Tests for the !live command: contest blocks, VIP cash bullets and VIP presence."""

import pytest

from dk_results.bot import discord_bot
from dk_results.persistence.contestdatabase import VipCashStatus
from tests.bot.discord_bot_fakes import DummySport, DummySportTwo, FakeCtx, _ctx, _settings


def test_live_contest_block_keeps_draftkings_link_separate_from_dashboard_and_sheet(monkeypatch):
    monkeypatch.setattr(discord_bot, "_sheet_link", lambda _settings, _sport: "<https://sheet.example/nba>")
    monkeypatch.setattr(discord_bot, "_format_time_since", lambda _start_date: None)
    monkeypatch.setattr(discord_bot, "_vip_presence_for_contest", lambda _dk_id: None)

    msg = discord_bot._format_live_contest_block(
        _settings(dashboard_base_url="https://dashboard.example/"), 1, "Contest", "2000-01-01", "NBA", None, [], None
    )

    assert msg.endswith(
        "• 🔗 DK: [1](<https://www.draftkings.com/contest/gamecenter/1#/>)\n"
        "• 📈 Dashboard: [NBA](<https://dashboard.example/live/nba>) | 📊 Sheet: [NBA](<https://sheet.example/nba>)"
    )


@pytest.mark.asyncio
async def test_live_lists_all_live_contests(monkeypatch):
    monkeypatch.setattr(discord_bot, "_sport_choices", lambda: {"nba": DummySport, "nfl": DummySportTwo})
    monkeypatch.setattr(discord_bot, "_sheet_link", lambda _settings, _sport: None)
    monkeypatch.setattr(discord_bot, "_vip_presence_for_contest", lambda _dk_id: None)
    monkeypatch.setattr(discord_bot, "_format_time_since", lambda _start_date: None)

    captured = {}

    class FakeContestDatabase:
        def __init__(self, *args, **kwargs):
            captured["init_args"] = args
            captured["init_kwargs"] = kwargs

        def get_live_contests(self, sports=None, entry_fee=25, keyword="%"):
            captured["sports"] = sports
            return [
                (1, "ContestA", None, None, "2000-01-01", "NBA"),
                (2, "ContestB", None, None, "2000-01-02", "NFL"),
            ]

        def get_cash_line(self, dk_id):
            return None

        def get_vip_cash_status(self, dk_id):
            return []

        def close(self):
            captured["closed"] = True

    monkeypatch.setattr(discord_bot, "ContestDatabase", FakeContestDatabase)

    ctx = FakeCtx()
    await discord_bot.live(_settings(), _ctx(ctx))

    assert captured["sports"] == ["NBA", "NFL"]
    assert captured.get("closed") is True
    assert ctx.sent == [
        "Live: 🏀 NBA — ContestA\n"
        "• 🕒 2000-01-01\n"
        "• 🔗 DK: [1](<https://www.draftkings.com/contest/gamecenter/1#/>) | 📊 Sheet: n/a\n\n"
        "Live: 🏈 NFL — ContestB\n"
        "• 🕒 2000-01-02\n"
        "• 🔗 DK: [2](<https://www.draftkings.com/contest/gamecenter/2#/>) | 📊 Sheet: n/a"
    ]


@pytest.mark.asyncio
async def test_live_shows_vip_presence_per_contest(monkeypatch):
    monkeypatch.setattr(discord_bot, "_sport_choices", lambda: {"nba": DummySport, "nfl": DummySportTwo})
    monkeypatch.setattr(discord_bot, "_sheet_link", lambda _settings, _sport: None)
    monkeypatch.setattr(discord_bot, "_format_time_since", lambda _start_date: None)

    def fake_presence(dk_id):
        return {1: "present", 2: "absent"}.get(dk_id)

    monkeypatch.setattr(discord_bot, "_vip_presence_for_contest", fake_presence)

    class FakeContestDatabase:
        def __init__(self, *args, **kwargs):
            pass

        def get_live_contests(self, sports=None, entry_fee=25, keyword="%"):
            return [
                (1, "ContestA", None, None, "2000-01-01", "NBA"),
                (2, "ContestB", None, None, "2000-01-02", "NFL"),
            ]

        def get_cash_line(self, dk_id):
            return None

        def get_vip_cash_status(self, dk_id):
            return []

        def close(self):
            pass

    monkeypatch.setattr(discord_bot, "ContestDatabase", FakeContestDatabase)

    ctx = FakeCtx()
    await discord_bot.live(_settings(), _ctx(ctx))

    assert ctx.sent == [
        "Live: 🏀 NBA — ContestA\n"
        "• 🕒 2000-01-01\n"
        "• 🔗 DK: [1](<https://www.draftkings.com/contest/gamecenter/1#/>) | 📊 Sheet: n/a\n"
        "• ⭐ VIP: present\n\n"
        "Live: 🏈 NFL — ContestB\n"
        "• 🕒 2000-01-02\n"
        "• 🔗 DK: [2](<https://www.draftkings.com/contest/gamecenter/2#/>) | 📊 Sheet: n/a\n"
        "• ⭐ VIP: absent"
    ]


@pytest.mark.asyncio
async def test_live_shows_vip_cash_bullets(monkeypatch):
    monkeypatch.setattr(discord_bot, "_sport_choices", lambda: {"nba": DummySport})
    monkeypatch.setattr(discord_bot, "_sheet_link", lambda _settings, _sport: None)
    monkeypatch.setattr(discord_bot, "_format_time_since", lambda _start_date: None)
    # Presence stubbed to a real verdict to prove it's suppressed once cash bullets render.
    monkeypatch.setattr(discord_bot, "_vip_presence_for_contest", lambda _dk_id: "present")

    class FakeContestDatabase:
        def __init__(self, *args, **kwargs):
            pass

        def get_live_contests(self, sports=None, entry_fee=25, keyword="%"):
            return [(1, "ContestA", None, 20, "2000-01-01", "NBA")]

        def get_cash_line(self, dk_id):
            return (5, 100.0)

        def get_vip_cash_status(self, dk_id):
            return [
                VipCashStatus(vip_name="VipA", rank=3, points=150.0),
                VipCashStatus(vip_name="VipB", rank=10, points=50.0),
            ]

        def close(self):
            pass

    monkeypatch.setattr(discord_bot, "ContestDatabase", FakeContestDatabase)

    ctx = FakeCtx()
    await discord_bot.live(_settings(), _ctx(ctx))

    assert ctx.sent == [
        "Live: 🏀 NBA — ContestA\n"
        "• 🕒 2000-01-01\n"
        "• 🔗 DK: [1](<https://www.draftkings.com/contest/gamecenter/1#/>) | 📊 Sheet: n/a\n"
        "• 🤑 VipA: 150.0 pts (+50.0 pts), rank 3 (cash: top 20)\n"
        "• ☠️ VipB: 50.0 pts (-50.0 pts), rank 10 (cash: top 20)"
    ]


@pytest.mark.asyncio
async def test_live_shows_elapsed_time_since_start(monkeypatch):
    monkeypatch.setattr(discord_bot, "_sport_choices", lambda: {"nba": DummySport})
    monkeypatch.setattr(discord_bot, "_sheet_link", lambda _settings, _sport: None)
    monkeypatch.setattr(discord_bot, "_vip_presence_for_contest", lambda _dk_id: None)
    monkeypatch.setattr(discord_bot, "_format_time_since", lambda _start_date: "started 2h13m ago")

    class FakeContestDatabase:
        def __init__(self, *args, **kwargs):
            pass

        def get_live_contests(self, sports=None, entry_fee=25, keyword="%"):
            return [(1, "ContestA", None, None, "2000-01-01", "NBA")]

        def get_cash_line(self, dk_id):
            return None

        def get_vip_cash_status(self, dk_id):
            return []

        def close(self):
            pass

    monkeypatch.setattr(discord_bot, "ContestDatabase", FakeContestDatabase)

    ctx = FakeCtx()
    await discord_bot.live(_settings(), _ctx(ctx))

    assert ctx.sent == [
        "Live: 🏀 NBA — ContestA\n"
        "• 🕒 2000-01-01 (started 2h13m ago)\n"
        "• 🔗 DK: [1](<https://www.draftkings.com/contest/gamecenter/1#/>) | 📊 Sheet: n/a"
    ]


def test_format_vip_cash_bullets_empty_returns_no_bullets():
    assert discord_bot._format_vip_cash_bullets([], (5, 100.0), 20) == []


def test_format_vip_cash_bullets_missing_cash_line_marks_not_cashing():
    statuses = [VipCashStatus(vip_name="VipA", rank=1, points=200.0)]
    assert discord_bot._format_vip_cash_bullets(statuses, None, None) == ["• ☠️ VipA: 200.0 pts, rank 1"]


def test_format_vip_cash_bullets_includes_delta_and_cash_context():
    statuses = [
        VipCashStatus(vip_name="alice", rank=12, points=163.0),
        VipCashStatus(vip_name="bob", rank=34, points=142.3),
    ]
    bullets = discord_bot._format_vip_cash_bullets(statuses, (20, 150.5), 20)
    assert bullets == [
        "• 🤑 alice: 163.0 pts (+12.5 pts), rank 12 (cash: top 20)",
        "• ☠️ bob: 142.3 pts (-8.2 pts), rank 34 (cash: top 20)",
    ]


def test_format_vip_cash_bullets_omits_cash_context_when_positions_paid_missing():
    statuses = [VipCashStatus(vip_name="alice", rank=1, points=100.0)]
    bullets = discord_bot._format_vip_cash_bullets(statuses, (5, 90.0), None)
    assert bullets == ["• 🤑 alice: 100.0 pts (+10.0 pts), rank 1"]


@pytest.mark.asyncio
async def test_live_no_contests(monkeypatch):
    monkeypatch.setattr(discord_bot, "_sport_choices", lambda: {"nba": DummySport, "nfl": DummySportTwo})

    class FakeContestDatabase:
        def __init__(self, *args, **kwargs):
            pass

        def get_live_contests(self, sports=None, entry_fee=25, keyword="%"):
            return []

        def get_cash_line(self, dk_id):
            return None

        def get_vip_cash_status(self, dk_id):
            return []

        def close(self):
            pass

    monkeypatch.setattr(discord_bot, "ContestDatabase", FakeContestDatabase)

    ctx = FakeCtx()
    await discord_bot.live(_settings(), _ctx(ctx))

    assert ctx.sent == ["No live contests found."]


def test_vip_presence_for_contest_present(monkeypatch, tmp_path):
    db_path = tmp_path / "contests.db"
    monkeypatch.setattr(discord_bot, "_db_path", lambda: str(db_path))
    conn = discord_bot.sqlite3.connect(str(db_path))
    discord_bot.NotificationStore(conn).upsert_presence(1, "present")
    conn.close()

    assert discord_bot._vip_presence_for_contest(1) == "present"


def test_vip_presence_for_contest_absent(monkeypatch, tmp_path):
    db_path = tmp_path / "contests.db"
    monkeypatch.setattr(discord_bot, "_db_path", lambda: str(db_path))
    conn = discord_bot.sqlite3.connect(str(db_path))
    discord_bot.NotificationStore(conn).upsert_presence(2, "absent")
    conn.close()

    assert discord_bot._vip_presence_for_contest(2) == "absent"


def test_vip_presence_for_contest_unknown_suppressed(monkeypatch, tmp_path):
    db_path = tmp_path / "contests.db"
    monkeypatch.setattr(discord_bot, "_db_path", lambda: str(db_path))
    conn = discord_bot.sqlite3.connect(str(db_path))
    discord_bot.NotificationStore(conn).upsert_presence(3, "unknown_capped")
    conn.close()

    assert discord_bot._vip_presence_for_contest(3) is None


def test_vip_presence_for_contest_no_cached_row(monkeypatch, tmp_path):
    db_path = tmp_path / "contests.db"
    monkeypatch.setattr(discord_bot, "_db_path", lambda: str(db_path))

    assert discord_bot._vip_presence_for_contest(999) is None
