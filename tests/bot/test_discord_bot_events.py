"""Tests for the channel check and the bot's event handlers."""

import types

import pytest
from discord.ext import commands

from dk_results.bot import discord_bot
from tests.bot.discord_bot_fakes import FakeCtx, _ctx, _settings


@pytest.mark.asyncio
async def test_limit_to_channel_allows_when_not_set(monkeypatch):
    ctx = FakeCtx()
    assert await discord_bot.limit_to_channel(_settings(), _ctx(ctx)) is True


@pytest.mark.asyncio
async def test_limit_to_channel_blocks_other_channels(monkeypatch):
    ctx = FakeCtx()
    ctx.channel.id = 999
    assert await discord_bot.limit_to_channel(_settings(discord_channel_id=123), _ctx(ctx)) is False


@pytest.mark.asyncio
async def test_on_command_error_unknown_command(monkeypatch):
    ctx = FakeCtx()

    # Should ignore CommandNotFound silently.
    async def _dummy(ctx):
        return None

    dummy_command = commands.Command(_dummy, name="fake")
    await discord_bot.on_command_error(_ctx(ctx), commands.CommandNotFound(f"Command {dummy_command} not found"))
    assert ctx.sent == []


@pytest.mark.asyncio
async def test_on_command_error_other_error(monkeypatch):
    ctx = FakeCtx()
    await discord_bot.on_command_error(_ctx(ctx), RuntimeError("boom"))
    assert ctx.sent == ["Something went wrong running that command."]


@pytest.mark.asyncio
async def test_on_command_error_logs_wrapped_traceback(caplog):
    """CommandInvokeError should be unwrapped so the real cause's traceback is logged."""
    ctx = FakeCtx()
    try:
        raise ValueError("underlying failure")
    except ValueError as exc:
        wrapped = commands.CommandInvokeError(exc)

    with caplog.at_level("ERROR", logger="dk_results.bot.discord_bot"):
        await discord_bot.on_command_error(_ctx(ctx), wrapped)

    assert ctx.sent == ["Something went wrong running that command."]
    record = caplog.records[-1]
    assert "ValueError" in caplog.text
    assert "underlying failure" in caplog.text
    assert record.exc_info is not None
    assert record.exc_info[0] is ValueError
    assert record.exc_info[1].args == ("underlying failure",)


@pytest.mark.asyncio
async def test_on_ready_logs(monkeypatch):
    messages: list[str] = []

    def fake_info(msg, *args):
        messages.append(msg % args if args else msg)

    monkeypatch.setattr(discord_bot.logger, "info", fake_info)
    await discord_bot.on_ready("bot-user")
    assert any("Discord bot logged in" in msg for msg in messages)


@pytest.mark.asyncio
async def test_on_command_error_check_failure():
    ctx = types.SimpleNamespace(sent=[])

    async def _send(message: str):
        ctx.sent.append(message)

    ctx.send = _send

    await discord_bot.on_command_error(ctx, discord_bot.commands.CheckFailure())
    assert ctx.sent == []
