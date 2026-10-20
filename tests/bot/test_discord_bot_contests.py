"""Tests for the !contests command and its single live-contest lookup."""

import types

import pytest

from dk_results.bot import discord_bot
from tests.bot.discord_bot_fakes import DummySport, FakeCtx, _ctx


@pytest.mark.asyncio
async def test_contests_requires_sport(monkeypatch):
    monkeypatch.setattr(discord_bot, "_sport_choices", lambda: {"nba": DummySport})

    ctx = FakeCtx()
    await discord_bot.contests(_ctx(ctx))

    assert ctx.sent == ["Pick a sport: NBA"]


@pytest.mark.asyncio
async def test_contests_unknown_sport(monkeypatch):
    monkeypatch.setattr(discord_bot, "_sport_choices", lambda: {"nba": DummySport})

    ctx = FakeCtx()
    await discord_bot.contests(_ctx(ctx), "nfl")

    assert ctx.sent == ["Unknown sport 'nfl'. Allowed options: NBA"]


@pytest.mark.asyncio
async def test_contests_returns_live_contest(monkeypatch):
    monkeypatch.setattr(discord_bot, "_sport_choices", lambda: {"nba": DummySport})
    monkeypatch.setattr(
        discord_bot,
        "_fetch_live_contest",
        lambda sport_cls: (1, "Contest", None, None, "2000-01-01"),
    )
    monkeypatch.setattr(discord_bot, "_sheet_link", lambda _sport: None)
    monkeypatch.setattr(discord_bot, "_vip_presence_for_contest", lambda _dk_id: None)

    ctx = FakeCtx()
    await discord_bot.contests(_ctx(ctx), "nba")

    assert ctx.sent == [
        "Live: 🏀 NBA — Contest\n"
        "• 🕒 2000-01-01\n"
        "• 🔗 DK: [1](<https://www.draftkings.com/contest/gamecenter/1#/>)\n"
        "• 📊 Sheet: n/a"
    ]


@pytest.mark.asyncio
async def test_contests_returns_live_contest_with_vip_present(monkeypatch):
    monkeypatch.setattr(discord_bot, "_sport_choices", lambda: {"nba": DummySport})
    monkeypatch.setattr(
        discord_bot,
        "_fetch_live_contest",
        lambda sport_cls: (1, "Contest", None, None, "2000-01-01"),
    )
    monkeypatch.setattr(discord_bot, "_sheet_link", lambda _sport: None)
    monkeypatch.setattr(discord_bot, "_vip_presence_for_contest", lambda _dk_id: "present")

    ctx = FakeCtx()
    await discord_bot.contests(_ctx(ctx), "nba")

    assert ctx.sent == [
        "Live: 🏀 NBA — Contest\n"
        "• 🕒 2000-01-01\n"
        "• 🔗 DK: [1](<https://www.draftkings.com/contest/gamecenter/1#/>)\n"
        "• 📊 Sheet: n/a\n"
        "• ⭐ VIP: present"
    ]


@pytest.mark.asyncio
async def test_contests_links_dashboard_before_sheet(monkeypatch):
    monkeypatch.setattr(discord_bot, "DASHBOARD_BASE_URL", "https://dashboard.example/")
    monkeypatch.setattr(discord_bot, "_sport_choices", lambda: {"nba": DummySport})
    monkeypatch.setattr(
        discord_bot,
        "_fetch_live_contest",
        lambda sport_cls: (1, "Contest", None, None, "2000-01-01"),
    )
    monkeypatch.setattr(discord_bot, "_sheet_link", lambda _sport: "<https://sheet.example/nba>")
    monkeypatch.setattr(discord_bot, "_vip_presence_for_contest", lambda _dk_id: None)

    ctx = FakeCtx()
    await discord_bot.contests(_ctx(ctx), "nba")

    assert ctx.sent[0].endswith(
        "• 📈 Dashboard: [NBA](<https://dashboard.example/live/nba>) | 📊 Sheet: [NBA](<https://sheet.example/nba>)"
    )


@pytest.mark.asyncio
async def test_contests_no_contest_found(monkeypatch):
    monkeypatch.setattr(discord_bot, "_sport_choices", lambda: {"nba": DummySport})
    monkeypatch.setattr(discord_bot, "_fetch_live_contest", lambda sport_cls: None)

    ctx = FakeCtx()
    await discord_bot.contests(_ctx(ctx), "nba")

    assert ctx.sent == ["No live contest found for NBA."]


def test_fetch_live_contest_closes_db(monkeypatch):
    captured = {}

    class FakeDB:
        def __init__(self, *args, **kwargs):
            pass

        def get_live_contest(self, _name, _fee, _keyword):
            return (1, "Contest", None, None, "2000-01-01")

        def close(self):
            captured["closed"] = True

    class DummySport:
        name = "NBA"
        sheet_min_entry_fee = 5
        keyword = "%"

    monkeypatch.setattr(discord_bot, "ContestDatabase", FakeDB)

    assert discord_bot._fetch_live_contest(DummySport) == (
        1,
        "Contest",
        None,
        None,
        "2000-01-01",
    )
    assert captured.get("closed") is True


@pytest.mark.asyncio
async def test_contests_invalid_sport_config(monkeypatch):
    class DummySport:
        name = None
        sheet_min_entry_fee = 5
        keyword = "%"

    monkeypatch.setattr(discord_bot, "_sport_choices", lambda: {"nba": DummySport})

    ctx = types.SimpleNamespace(sent=[])

    async def _send(message: str):
        ctx.sent.append(message)

    ctx.send = _send

    await discord_bot.contests(ctx, "nba")
    assert ctx.sent == ["Invalid sport configuration."]
