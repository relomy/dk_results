"""Tests for the !health, !help, !sports, !upcoming and !sankayadead commands."""

import pytest

from dk_results.bot import discord_bot


@pytest.mark.asyncio
async def test_health_reports_bot_and_host_uptime(monkeypatch, ctx, as_context):
    monkeypatch.setattr(discord_bot, "START_TIME", 0)
    monkeypatch.setattr(discord_bot.time, "time", lambda: 1000)
    monkeypatch.setattr(discord_bot, "_system_uptime_seconds", lambda: 200)

    await discord_bot.health(as_context(ctx))

    assert ctx.sent == ["alive. bot uptime: 16m 40s. host uptime: 3m 20s"]


@pytest.mark.asyncio
async def test_help_lists_commands(monkeypatch, ctx, as_context, dummy_sport, dummy_sport_two):
    monkeypatch.setattr(discord_bot, "_sport_choices", lambda: {"nba": dummy_sport, "nfl": dummy_sport_two})

    await discord_bot.help_command(as_context(ctx))

    message = ctx.sent[0]
    assert "!sankayadead" in message
    assert "!health" in message
    assert "!contests <sport>" in message
    assert "NBA" in message and "NFL" in message
    assert "!live" in message
    assert "!upcoming" in message
    assert "!sports" in message


@pytest.mark.asyncio
async def test_sports_lists_supported(monkeypatch, ctx, as_context, dummy_sport, dummy_sport_two):
    monkeypatch.setattr(discord_bot, "_sport_choices", lambda: {"nba": dummy_sport, "nfl": dummy_sport_two})
    await discord_bot.sports(as_context(ctx))
    assert ctx.sent == ["Supported sports: NBA, NFL"]


@pytest.mark.asyncio
async def test_upcoming_lists_next_per_sport(monkeypatch, ctx, as_context, dummy_sport, dummy_sport_two):
    monkeypatch.setattr(discord_bot, "_sport_choices", lambda: {"nba": dummy_sport, "nfl": dummy_sport_two})

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

    await discord_bot.upcoming(as_context(ctx))

    assert ctx.sent == [
        "NBA: name=MatchNBA, start_date=2000-01-02, url=<https://www.draftkings.com/contest/gamecenter/10#/>\n"
        "NFL: name=AnyNFL, start_date=2000-01-04 (failed criteria), url=<https://www.draftkings.com/contest/gamecenter/21#/>"
    ]


@pytest.mark.asyncio
async def test_sankayadead_sends(ctx, as_context):

    await discord_bot.sankayadead(as_context(ctx))
    assert ctx.sent == ["ya man"]


@pytest.mark.asyncio
async def test_upcoming_returns_without_lines(monkeypatch, ctx, as_context, dummy_sport):
    class FakeDB:
        def __init__(self, *args, **kwargs):
            pass

        def get_next_upcoming_contest_any(self, _sport):
            return None

        def get_next_upcoming_contest(self, _sport, entry_fee=25, keyword="%"):
            return None

        def close(self):
            return None

    monkeypatch.setattr(discord_bot, "_sport_choices", lambda: {"nba": dummy_sport})
    monkeypatch.setattr(discord_bot, "ContestDatabase", FakeDB)

    await discord_bot.upcoming(as_context(ctx))
    assert ctx.sent == []
