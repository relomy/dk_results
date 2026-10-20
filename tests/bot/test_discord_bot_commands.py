"""Tests for the !health, !help, !sports, !upcoming and !sankayadead commands."""

import types

import pytest

from dk_results.bot import discord_bot
from tests.bot.discord_bot_fakes import DummySport, DummySportTwo, FakeCtx, _ctx


@pytest.mark.asyncio
async def test_health_reports_bot_and_host_uptime(monkeypatch):
    monkeypatch.setattr(discord_bot, "START_TIME", 0)
    monkeypatch.setattr(discord_bot.time, "time", lambda: 1000)
    monkeypatch.setattr(discord_bot, "_system_uptime_seconds", lambda: 200)

    ctx = FakeCtx()
    await discord_bot.health(_ctx(ctx))

    assert ctx.sent == ["alive. bot uptime: 16m 40s. host uptime: 3m 20s"]


@pytest.mark.asyncio
async def test_help_lists_commands(monkeypatch):
    monkeypatch.setattr(discord_bot, "_sport_choices", lambda: {"nba": DummySport, "nfl": DummySportTwo})

    ctx = FakeCtx()
    await discord_bot.help_command(_ctx(ctx))

    message = ctx.sent[0]
    assert "!sankayadead" in message
    assert "!health" in message
    assert "!contests <sport>" in message
    assert "NBA" in message and "NFL" in message
    assert "!live" in message
    assert "!upcoming" in message
    assert "!sports" in message


@pytest.mark.asyncio
async def test_sports_lists_supported(monkeypatch):
    monkeypatch.setattr(discord_bot, "_sport_choices", lambda: {"nba": DummySport, "nfl": DummySportTwo})
    ctx = FakeCtx()
    await discord_bot.sports(_ctx(ctx))
    assert ctx.sent == ["Supported sports: NBA, NFL"]


@pytest.mark.asyncio
async def test_upcoming_lists_next_per_sport(monkeypatch):
    monkeypatch.setattr(discord_bot, "_sport_choices", lambda: {"nba": DummySport, "nfl": DummySportTwo})

    class FakeContestDatabase:
        def __init__(self, *args, **kwargs):
            pass

        def get_next_upcoming_contest_any(self, sport: str):
            if sport == "NBA":
                return (11, "AnyNBA", None, None, "2000-01-03")
            if sport == "NFL":
                return (21, "AnyNFL", None, None, "2000-01-04")
            return None

        def get_next_upcoming_contest(self, sport: str, entry_fee=25, keyword="%"):
            if sport == "NBA":
                return (10, "MatchNBA", None, None, "2000-01-02")
            return None

        def close(self):
            pass

    monkeypatch.setattr(discord_bot, "ContestDatabase", FakeContestDatabase)

    ctx = FakeCtx()
    await discord_bot.upcoming(_ctx(ctx))

    assert ctx.sent == [
        "NBA: name=MatchNBA, start_date=2000-01-02, url=<https://www.draftkings.com/contest/gamecenter/10#/>\n"
        "NFL: name=AnyNFL, start_date=2000-01-04 (failed criteria), url=<https://www.draftkings.com/contest/gamecenter/21#/>"
    ]


@pytest.mark.asyncio
async def test_sankayadead_sends():
    ctx = types.SimpleNamespace(sent=[])

    async def _send(message: str):
        ctx.sent.append(message)

    ctx.send = _send

    await discord_bot.sankayadead(ctx)
    assert ctx.sent == ["ya man"]


@pytest.mark.asyncio
async def test_upcoming_returns_without_lines(monkeypatch):
    class DummySport:
        name = "NBA"
        sheet_min_entry_fee = 5
        keyword = "%"

    class FakeDB:
        def __init__(self, *args, **kwargs):
            pass

        def get_next_upcoming_contest_any(self, _sport):
            return None

        def get_next_upcoming_contest(self, _sport, entry_fee=25, keyword="%"):
            return None

        def close(self):
            return None

    monkeypatch.setattr(discord_bot, "_sport_choices", lambda: {"nba": DummySport})
    monkeypatch.setattr(discord_bot, "ContestDatabase", FakeDB)

    ctx = types.SimpleNamespace(sent=[])

    async def _send(message: str):
        ctx.sent.append(message)

    ctx.send = _send

    await discord_bot.upcoming(ctx)
    assert ctx.sent == []
