import types

import pytest
from discord.ext import commands

from bot import discord_bot


class FakeCtx:
    def __init__(self):
        self.sent = []
        self.channel = types.SimpleNamespace(id=None)

    async def send(self, message: str):
        self.sent.append(message)


class DummySport:
    name = "NBA"
    sheet_min_entry_fee = 5
    keyword = "%"


class DummySportTwo:
    name = "NFL"
    sheet_min_entry_fee = 5
    keyword = "%"


@pytest.mark.asyncio
async def test_health_reports_bot_and_host_uptime(monkeypatch):
    monkeypatch.setattr(discord_bot, "START_TIME", 0)
    monkeypatch.setattr(discord_bot.time, "time", lambda: 1000)
    monkeypatch.setattr(discord_bot, "_system_uptime_seconds", lambda: 200)

    ctx = FakeCtx()
    await discord_bot.health(ctx)

    assert ctx.sent == ["alive. bot uptime: 16m 40s. host uptime: 3m 20s"]


def test_format_uptime_long():
    assert discord_bot._format_uptime(90061) == "1d 1h 1m 1s"


def test_system_uptime_seconds_parses(monkeypatch):
    def fake_open(path, mode="r", *args, **kwargs):
        class DummyFile:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return "123.45 0.00"

        return DummyFile()

    monkeypatch.setattr("builtins.open", fake_open)

    assert discord_bot._system_uptime_seconds() == pytest.approx(123.45)


@pytest.mark.asyncio
async def test_contests_requires_sport(monkeypatch):
    monkeypatch.setattr(discord_bot, "_sport_choices", lambda: {"nba": DummySport})

    ctx = FakeCtx()
    await discord_bot.contests(ctx)

    assert ctx.sent == ["Pick a sport: NBA"]


@pytest.mark.asyncio
async def test_contests_unknown_sport(monkeypatch):
    monkeypatch.setattr(discord_bot, "_sport_choices", lambda: {"nba": DummySport})

    ctx = FakeCtx()
    await discord_bot.contests(ctx, "nfl")

    assert ctx.sent == ["Unknown sport 'nfl'. Allowed options: NBA"]


@pytest.mark.asyncio
async def test_contests_returns_live_contest(monkeypatch):
    monkeypatch.setattr(discord_bot, "_sport_choices", lambda: {"nba": DummySport})
    monkeypatch.setattr(
        discord_bot, "_fetch_live_contest", lambda sport_cls: (1, "Contest", None, None, "2024-01-01")
    )

    ctx = FakeCtx()
    await discord_bot.contests(ctx, "nba")

    assert ctx.sent == [
        "NBA: dk_id=1, name=Contest, start_date=2024-01-01, url=<https://www.draftkings.com/contest/gamecenter/1#/>"
    ]


@pytest.mark.asyncio
async def test_live_lists_all_live_contests(monkeypatch):
    monkeypatch.setattr(
        discord_bot, "_sport_choices", lambda: {"nba": DummySport, "nfl": DummySportTwo}
    )

    captured = {}

    class FakeContestDatabase:
        def __init__(self, *args, **kwargs):
            captured["init_args"] = args
            captured["init_kwargs"] = kwargs

        def get_live_contests(self, sports=None, entry_fee=25, keyword="%"):
            captured["sports"] = sports
            return [
                (1, "ContestA", None, None, "2024-01-01", "NBA"),
                (2, "ContestB", None, None, "2024-01-02", "NFL"),
            ]

        def close(self):
            captured["closed"] = True

    monkeypatch.setattr(discord_bot, "ContestDatabase", FakeContestDatabase)

    ctx = FakeCtx()
    await discord_bot.live(ctx)

    assert captured["sports"] == ["NBA", "NFL"]
    assert captured.get("closed") is True
    assert ctx.sent == [
        "NBA: dk_id=1, name=ContestA, start_date=2024-01-01, url=<https://www.draftkings.com/contest/gamecenter/1#/>\n"
        "NFL: dk_id=2, name=ContestB, start_date=2024-01-02, url=<https://www.draftkings.com/contest/gamecenter/2#/>"
    ]


@pytest.mark.asyncio
async def test_live_no_contests(monkeypatch):
    monkeypatch.setattr(
        discord_bot, "_sport_choices", lambda: {"nba": DummySport, "nfl": DummySportTwo}
    )

    class FakeContestDatabase:
        def __init__(self, *args, **kwargs):
            pass

        def get_live_contests(self, sports=None, entry_fee=25, keyword="%"):
            return []

        def close(self):
            pass

    monkeypatch.setattr(discord_bot, "ContestDatabase", FakeContestDatabase)

    ctx = FakeCtx()
    await discord_bot.live(ctx)

    assert ctx.sent == ["No live contests found."]


@pytest.mark.asyncio
async def test_limit_to_channel_allows_when_not_set(monkeypatch):
    monkeypatch.setattr(discord_bot, "ALLOWED_CHANNEL_ID", None)
    ctx = FakeCtx()
    assert await discord_bot.limit_to_channel(ctx) is True


@pytest.mark.asyncio
async def test_limit_to_channel_blocks_other_channels(monkeypatch):
    monkeypatch.setattr(discord_bot, "ALLOWED_CHANNEL_ID", 123)
    ctx = FakeCtx()
    ctx.channel.id = 999
    assert await discord_bot.limit_to_channel(ctx) is False


def test_channel_id_from_env_valid(monkeypatch):
    monkeypatch.setenv("DISCORD_CHANNEL_ID", "12345")
    assert discord_bot._channel_id_from_env() == 12345


def test_channel_id_from_env_invalid(monkeypatch, caplog):
    caplog.set_level("WARNING")
    monkeypatch.setenv("DISCORD_CHANNEL_ID", "abc")
    assert discord_bot._channel_id_from_env() is None
    assert any("not a valid integer" in msg for msg in caplog.messages)


@pytest.mark.asyncio
async def test_contests_no_contest_found(monkeypatch):
    monkeypatch.setattr(discord_bot, "_sport_choices", lambda: {"nba": DummySport})
    monkeypatch.setattr(discord_bot, "_fetch_live_contest", lambda sport_cls: None)

    ctx = FakeCtx()
    await discord_bot.contests(ctx, "nba")

    assert ctx.sent == ["No live contest found for NBA."]


@pytest.mark.asyncio
async def test_on_command_error_unknown_command(monkeypatch):
    ctx = FakeCtx()
    # Should ignore CommandNotFound silently.
    async def _dummy(ctx):
        return None

    dummy_command = commands.Command(_dummy, name="fake")
    await discord_bot.on_command_error(ctx, commands.CommandNotFound(f"Command {dummy_command} not found"))
    assert ctx.sent == []


@pytest.mark.asyncio
async def test_on_command_error_other_error(monkeypatch):
    ctx = FakeCtx()
    await discord_bot.on_command_error(ctx, RuntimeError("boom"))
    assert ctx.sent == ["Something went wrong running that command."]


def test_main_requires_token(monkeypatch):
    monkeypatch.setattr(discord_bot, "BOT_TOKEN", None)
    with pytest.raises(RuntimeError):
        discord_bot.main()


@pytest.mark.asyncio
async def test_help_lists_commands(monkeypatch):
    monkeypatch.setattr(discord_bot, "_sport_choices", lambda: {"nba": DummySport, "nfl": DummySportTwo})

    ctx = FakeCtx()
    await discord_bot.help_command(ctx)

    message = ctx.sent[0]
    assert "!sankayadead" in message
    assert "!health" in message
    assert "!contests <sport>" in message
    assert "NBA" in message and "NFL" in message
    assert "!live" in message
    assert "!sports" in message


@pytest.mark.asyncio
async def test_sports_lists_supported(monkeypatch):
    monkeypatch.setattr(discord_bot, "_sport_choices", lambda: {"nba": DummySport, "nfl": DummySportTwo})
    ctx = FakeCtx()
    await discord_bot.sports(ctx)
    assert ctx.sent == ["Supported sports: NBA, NFL"]
