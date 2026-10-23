"""Tests for the bot's runtime configuration and its main() entry point."""

import pytest

from dk_results.bot import discord_bot
from tests.bot.discord_bot_fakes import DummySport, FakeCtx, _ctx, _settings


def test_module_main_executes(monkeypatch, tmp_path):
    captured = {}
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "tok")
    monkeypatch.setenv("DISCORD_LOG_FILE", str(tmp_path / "discord.log"))

    def fake_run(self, token):
        captured["token"] = token

    monkeypatch.setattr("discord.ext.commands.Bot.run", fake_run)

    discord_bot.main()

    assert captured["token"] == "tok"


def test_main_requires_token(monkeypatch):
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "")
    with pytest.raises(RuntimeError):
        discord_bot.main()


def test_sheet_link_requires_spreadsheet_id():
    settings = _settings(spreadsheet_id=None, sheet_gid_map={"NBA": 123})
    assert discord_bot._sheet_link(settings, "NBA") is None


def test_sheet_link_missing_gid():
    settings = _settings(spreadsheet_id="sheet", sheet_gid_map={"NBA": 123})
    assert discord_bot._sheet_link(settings, "NFL") is None


def test_sheet_link_builds_url():
    settings = _settings(spreadsheet_id="sheet", sheet_gid_map={"NBA": 123})
    assert discord_bot._sheet_link(settings, "NBA") == "<https://docs.google.com/spreadsheets/d/sheet/edit#gid=123>"


def test_sport_sheet_title_prefers_sheet_name():
    class DummySport:
        name = "NBA"
        sheet_name = "NBA Sheet"

    class DummySportNoSheet:
        name = "NFL"

    assert discord_bot._sport_sheet_title(DummySport) == "NBA Sheet"
    assert discord_bot._sport_sheet_title(DummySportNoSheet) == "NFL"


def test_configure_discord_log_file_handles_exception(monkeypatch):
    class BoomHandler:
        def __init__(self, *args, **kwargs):
            raise RuntimeError("boom")

    monkeypatch.setattr(discord_bot.logging, "FileHandler", BoomHandler)
    discord_bot._configure_discord_log_file(_settings())


def test_sport_choices_uses_the_built_in_registry():
    class DummySport(discord_bot.Sport):
        name = "DummySport"

    choices = discord_bot._sport_choices()
    assert "nflshowdown" in choices
    assert "dummysport" not in choices


def test_db_path_uses_dfs_common_state(monkeypatch):
    monkeypatch.setattr(discord_bot.state, "contests_db_path", lambda: "/tmp/contests.db")
    assert discord_bot._db_path() == "/tmp/contests.db"


def test_main_runs_bot(monkeypatch):
    captured = {}
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "tok")

    def fake_run(_self, token):
        captured["token"] = token

    def fake_create_bot(settings):
        captured["settings"] = settings
        return type("Bot", (), {"run": fake_run})()

    monkeypatch.setattr(discord_bot, "create_bot", fake_create_bot)
    discord_bot.main()
    assert captured["token"] == "tok"
    assert captured["settings"].bot_token == "tok"


@pytest.mark.asyncio
async def test_create_bot_registered_commands_use_the_injected_settings(monkeypatch):
    monkeypatch.setattr(discord_bot, "_sport_choices", lambda: {"nba": DummySport})
    monkeypatch.setattr(discord_bot, "_fetch_live_contest", lambda sport_cls: (1, "Contest", None, None, "2000-01-01"))
    monkeypatch.setattr(discord_bot, "_vip_presence_for_contest", lambda _dk_id: None)
    settings = _settings(
        spreadsheet_id="sheet",
        sheet_gid_map={"NBA": 123},
        allowed_channel_id=123,
    )

    bot = discord_bot.create_bot(settings)

    ctx = FakeCtx()
    ctx.channel.id = 123
    await bot.get_command("contests").callback(_ctx(ctx), "nba")
    assert "https://docs.google.com/spreadsheets/d/sheet/edit#gid=123" in ctx.sent[0]

    other = FakeCtx()
    other.channel.id = 999
    assert [await check(_ctx(other)) for check in bot._checks] == [False]
