import datetime
import types
from typing import cast

import pytest
from discord.ext import commands

from bot import discord_bot


class FakeCtx:
    def __init__(self):
        self.sent = []
        self.channel = types.SimpleNamespace(id=None)

    async def send(self, message: str):
        self.sent.append(message)


def _ctx(ctx: FakeCtx) -> commands.Context:
    return cast(commands.Context, ctx)


def test_format_time_until_future():
    now = datetime.datetime.now().replace(microsecond=0)
    future = now + datetime.timedelta(minutes=13, seconds=30)
    past = now - datetime.timedelta(minutes=1)

    assert discord_bot._format_time_until(future.isoformat(sep=" ")) == "⏳ 13m"
    assert discord_bot._format_time_until(past.isoformat(sep=" ")) is None


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
    await discord_bot.health(_ctx(ctx))

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

    ctx = FakeCtx()
    await discord_bot.contests(_ctx(ctx), "nba")

    assert ctx.sent == [
        "sport=NBA: dk_id=1, name=Contest, start_date=2000-01-01, url=<https://www.draftkings.com/contest/gamecenter/1#/>"
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
                (1, "ContestA", None, None, "2000-01-01", "NBA"),
                (2, "ContestB", None, None, "2000-01-02", "NFL"),
            ]

        def close(self):
            captured["closed"] = True

    monkeypatch.setattr(discord_bot, "ContestDatabase", FakeContestDatabase)

    ctx = FakeCtx()
    await discord_bot.live(_ctx(ctx))

    assert captured["sports"] == ["NBA", "NFL"]
    assert captured.get("closed") is True
    assert ctx.sent == [
        "🏀 NBA — ContestA\n"
        "• 🕒 2000-01-01\n"
        "• 🔗 DK: <https://www.draftkings.com/contest/gamecenter/1#/>\n"
        "• 📊 Sheet: n/a\n"
        "🏈 NFL — ContestB\n"
        "• 🕒 2000-01-02\n"
        "• 🔗 DK: <https://www.draftkings.com/contest/gamecenter/2#/>\n"
        "• 📊 Sheet: n/a"
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
    await discord_bot.live(_ctx(ctx))

    assert ctx.sent == ["No live contests found."]


@pytest.mark.asyncio
async def test_limit_to_channel_allows_when_not_set(monkeypatch):
    monkeypatch.setattr(discord_bot, "ALLOWED_CHANNEL_ID", None)
    ctx = FakeCtx()
    assert await discord_bot.limit_to_channel(_ctx(ctx)) is True


@pytest.mark.asyncio
async def test_limit_to_channel_blocks_other_channels(monkeypatch):
    monkeypatch.setattr(discord_bot, "ALLOWED_CHANNEL_ID", 123)
    ctx = FakeCtx()
    ctx.channel.id = 999
    assert await discord_bot.limit_to_channel(_ctx(ctx)) is False


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


@pytest.mark.asyncio
async def test_contests_no_contest_found(monkeypatch):
    monkeypatch.setattr(discord_bot, "_sport_choices", lambda: {"nba": DummySport})
    monkeypatch.setattr(discord_bot, "_fetch_live_contest", lambda sport_cls: None)

    ctx = FakeCtx()
    await discord_bot.contests(_ctx(ctx), "nba")

    assert ctx.sent == ["No live contest found for NBA."]


@pytest.mark.asyncio
async def test_on_command_error_unknown_command(monkeypatch):
    ctx = FakeCtx()

    # Should ignore CommandNotFound silently.
    async def _dummy(ctx):
        return None

    dummy_command = commands.Command(_dummy, name="fake")
    await discord_bot.on_command_error(
        _ctx(ctx), commands.CommandNotFound(f"Command {dummy_command} not found")
    )
    assert ctx.sent == []


@pytest.mark.asyncio
async def test_on_command_error_other_error(monkeypatch):
    ctx = FakeCtx()
    await discord_bot.on_command_error(_ctx(ctx), RuntimeError("boom"))
    assert ctx.sent == ["Something went wrong running that command."]


def test_main_requires_token(monkeypatch):
    monkeypatch.setattr(discord_bot, "BOT_TOKEN", None)
    with pytest.raises(RuntimeError):
        discord_bot.main()


@pytest.mark.asyncio
async def test_help_lists_commands(monkeypatch):
    monkeypatch.setattr(
        discord_bot, "_sport_choices", lambda: {"nba": DummySport, "nfl": DummySportTwo}
    )

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
    monkeypatch.setattr(
        discord_bot, "_sport_choices", lambda: {"nba": DummySport, "nfl": DummySportTwo}
    )
    ctx = FakeCtx()
    await discord_bot.sports(_ctx(ctx))
    assert ctx.sent == ["Supported sports: NBA, NFL"]


@pytest.mark.asyncio
async def test_upcoming_lists_next_per_sport(monkeypatch):
    monkeypatch.setattr(
        discord_bot, "_sport_choices", lambda: {"nba": DummySport, "nfl": DummySportTwo}
    )

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
    assert (
        discord_bot._sheet_link("NBA")
        == "<https://docs.google.com/spreadsheets/d/sheet/edit#gid=123>"
    )


def test_sport_sheet_title_prefers_sheet_name():
    class DummySport:
        name = "NBA"
        sheet_name = "NBA Sheet"

    class DummySportNoSheet:
        name = "NFL"

    assert discord_bot._sport_sheet_title(DummySport) == "NBA Sheet"
    assert discord_bot._sport_sheet_title(DummySportNoSheet) == "NFL"


def test_sport_emoji_default():
    assert discord_bot._sport_emoji("UNKNOWN") == "🏟️"


def test_configure_discord_log_file_handles_exception(monkeypatch):
    class BoomHandler:
        def __init__(self, *args, **kwargs):
            raise RuntimeError("boom")

    monkeypatch.setattr(discord_bot.logging, "FileHandler", BoomHandler)
    discord_bot._configure_discord_log_file()


def test_sport_choices_includes_named():
    class DummySport(discord_bot.Sport):
        name = "DummySport"

    choices = discord_bot._sport_choices()
    assert "dummysport" in choices


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


def test_format_time_until_seconds_only(monkeypatch):
    class FixedDateTime(datetime.datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2024, 1, 1, 0, 0, 0, tzinfo=tz)

    monkeypatch.setattr(discord_bot.datetime, "datetime", FixedDateTime)

    assert discord_bot._format_time_until("2024-01-01 00:00:05") == "⏳ 5s"


def test_format_time_until_days_hours(monkeypatch):
    class FixedDateTime(datetime.datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2024, 1, 1, 0, 0, 0, tzinfo=tz)

    monkeypatch.setattr(discord_bot.datetime, "datetime", FixedDateTime)

    assert discord_bot._format_time_until("2024-01-02 02:03:00") == "⏳ 1d2h3m"


def test_format_time_until_invalid():
    assert discord_bot._format_time_until(None) is None


def test_system_uptime_seconds_missing_file(monkeypatch):
    def boom(*_args, **_kwargs):
        raise FileNotFoundError("nope")

    monkeypatch.setattr("builtins.open", boom)
    assert discord_bot._system_uptime_seconds() is None


@pytest.mark.asyncio
async def test_on_ready_logs(monkeypatch):
    messages: list[str] = []

    def fake_info(msg, *args):
        messages.append(msg % args if args else msg)

    monkeypatch.setattr(discord_bot.logger, "info", fake_info)
    await discord_bot.on_ready()
    assert any("Discord bot logged in" in msg for msg in messages)


@pytest.mark.asyncio
async def test_on_command_error_check_failure():
    ctx = types.SimpleNamespace(sent=[])

    async def _send(message: str):
        ctx.sent.append(message)

    ctx.send = _send

    await discord_bot.on_command_error(ctx, discord_bot.commands.CheckFailure())
    assert ctx.sent == []


@pytest.mark.asyncio
async def test_sankayadead_sends():
    ctx = types.SimpleNamespace(sent=[])

    async def _send(message: str):
        ctx.sent.append(message)

    ctx.send = _send

    await discord_bot.sankayadead(ctx)
    assert ctx.sent == ["ya man"]


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


def test_main_runs_bot(monkeypatch):
    captured = {}
    monkeypatch.setattr(discord_bot, "BOT_TOKEN", "tok")

    def fake_run(token):
        captured["token"] = token

    monkeypatch.setattr(discord_bot.bot, "run", fake_run)
    discord_bot.main()
    assert captured["token"] == "tok"
