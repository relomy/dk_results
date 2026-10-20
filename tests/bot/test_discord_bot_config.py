"""Tests for the bot's runtime configuration and its main() entry point."""

import pytest

from dk_results.bot import discord_bot


def test_module_main_executes(monkeypatch, tmp_path):
    captured = {}
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "tok")
    monkeypatch.setenv("DISCORD_LOG_FILE", str(tmp_path / "discord.log"))
    monkeypatch.setattr(discord_bot, "BOT_TOKEN", "tok")

    def fake_run(self, token):
        captured["token"] = token

    monkeypatch.setattr("discord.ext.commands.Bot.run", fake_run)

    discord_bot.main()

    assert captured["token"] == "tok"


def test_channel_id_from_env_valid(monkeypatch):
    monkeypatch.setenv("DISCORD_CHANNEL_ID", "12345")
    assert discord_bot._channel_id_from_env() == 12345


def test_channel_id_from_env_invalid(monkeypatch, caplog):
    captured = []
    monkeypatch.setattr(
        discord_bot.logger,
        "warning",
        lambda message, *args: captured.append(message % args if args else message),
    )
    monkeypatch.setenv("DISCORD_CHANNEL_ID", "abc")
    assert discord_bot._channel_id_from_env() is None
    assert any("not a valid integer" in msg for msg in captured)


def test_main_requires_token(monkeypatch):
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "")
    monkeypatch.setattr(discord_bot, "BOT_TOKEN", None)
    with pytest.raises(RuntimeError):
        discord_bot.main()


def test_load_sheet_gid_map_requires_env(monkeypatch):
    monkeypatch.setattr(discord_bot, "SHEET_GIDS_FILE", "")
    assert discord_bot._load_sheet_gid_map() == {}


def test_load_sheet_gid_map_missing_file(tmp_path, monkeypatch):
    monkeypatch.setattr(discord_bot, "SHEET_GIDS_FILE", str(tmp_path / "missing.yaml"))
    assert discord_bot._load_sheet_gid_map() == {}


def test_load_sheet_gid_map_invalid_yaml(tmp_path, monkeypatch):
    path = tmp_path / "gids.yaml"
    path.write_text("bad")
    monkeypatch.setattr(discord_bot, "SHEET_GIDS_FILE", str(path))

    def boom(_text):
        raise RuntimeError("boom")

    monkeypatch.setattr(discord_bot.yaml, "safe_load", boom)
    assert discord_bot._load_sheet_gid_map() == {}


def test_load_sheet_gid_map_non_dict(tmp_path, monkeypatch):
    path = tmp_path / "gids.yaml"
    path.write_text("- 1")
    monkeypatch.setattr(discord_bot, "SHEET_GIDS_FILE", str(path))
    monkeypatch.setattr(discord_bot.yaml, "safe_load", lambda _text: ["not-dict"])
    assert discord_bot._load_sheet_gid_map() == {}


def test_load_sheet_gid_map_filters_invalid_entries(tmp_path, monkeypatch):
    path = tmp_path / "gids.yaml"
    path.write_text("ignored")
    monkeypatch.setattr(discord_bot, "SHEET_GIDS_FILE", str(path))
    monkeypatch.setattr(
        discord_bot.yaml,
        "safe_load",
        lambda _text: {"NBA": 10, 1: "bad", "NFL": "oops"},
    )
    assert discord_bot._load_sheet_gid_map() == {"NBA": 10}


def test_sheet_link_requires_spreadsheet_id(monkeypatch):
    monkeypatch.setattr(discord_bot, "SPREADSHEET_ID", None)
    monkeypatch.setattr(discord_bot, "SHEET_GID_MAP", {"NBA": 123})
    assert discord_bot._sheet_link("NBA") is None


def test_sheet_link_missing_gid(monkeypatch):
    monkeypatch.setattr(discord_bot, "SPREADSHEET_ID", "sheet")
    monkeypatch.setattr(discord_bot, "SHEET_GID_MAP", {"NBA": 123})
    assert discord_bot._sheet_link("NFL") is None


def test_sheet_link_builds_url(monkeypatch):
    monkeypatch.setattr(discord_bot, "SPREADSHEET_ID", "sheet")
    monkeypatch.setattr(discord_bot, "SHEET_GID_MAP", {"NBA": 123})
    assert discord_bot._sheet_link("NBA") == "<https://docs.google.com/spreadsheets/d/sheet/edit#gid=123>"


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
    discord_bot._configure_discord_log_file()


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

    monkeypatch.setattr(discord_bot, "create_bot", lambda: type("Bot", (), {"run": fake_run})())
    discord_bot.main()
    assert captured["token"] == "tok"
