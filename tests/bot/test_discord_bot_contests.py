"""Tests for the !contests command and its single live-contest lookup."""

import pytest

from dk_results.bot import discord_bot


@pytest.mark.asyncio
async def test_contests_requires_sport(monkeypatch, ctx, as_context, make_settings, dummy_sport):
    monkeypatch.setattr(discord_bot, "_sport_choices", lambda: {"nba": dummy_sport})

    await discord_bot.contests(make_settings(), as_context(ctx))

    assert ctx.sent == ["Pick a sport: NBA"]


@pytest.mark.asyncio
async def test_contests_unknown_sport(monkeypatch, ctx, as_context, make_settings, dummy_sport):
    monkeypatch.setattr(discord_bot, "_sport_choices", lambda: {"nba": dummy_sport})

    await discord_bot.contests(make_settings(), as_context(ctx), "nfl")

    assert ctx.sent == ["Unknown sport 'nfl'. Allowed options: NBA"]


@pytest.mark.asyncio
async def test_contests_returns_live_contest(monkeypatch, ctx, as_context, make_settings, dummy_sport):
    monkeypatch.setattr(discord_bot, "_sport_choices", lambda: {"nba": dummy_sport})
    monkeypatch.setattr(
        discord_bot,
        "_fetch_live_contest",
        lambda sport_cls: (1, "Contest", None, None, "2000-01-01"),
    )
    monkeypatch.setattr(discord_bot, "_sheet_link", lambda _settings, _sport: None)
    monkeypatch.setattr(discord_bot, "_vip_presence_for_contest", lambda _dk_id: None)

    await discord_bot.contests(make_settings(), as_context(ctx), "nba")

    assert ctx.sent == [
        "Live: 🏀 NBA — Contest\n"
        "• 🕒 2000-01-01\n"
        "• 🔗 DK: [1](<https://www.draftkings.com/contest/gamecenter/1#/>)\n"
        "• 📊 Sheet: n/a"
    ]


@pytest.mark.asyncio
async def test_contests_returns_live_contest_with_vip_present(monkeypatch, ctx, as_context, make_settings, dummy_sport):
    monkeypatch.setattr(discord_bot, "_sport_choices", lambda: {"nba": dummy_sport})
    monkeypatch.setattr(
        discord_bot,
        "_fetch_live_contest",
        lambda sport_cls: (1, "Contest", None, None, "2000-01-01"),
    )
    monkeypatch.setattr(discord_bot, "_sheet_link", lambda _settings, _sport: None)
    monkeypatch.setattr(discord_bot, "_vip_presence_for_contest", lambda _dk_id: "present")

    await discord_bot.contests(make_settings(), as_context(ctx), "nba")

    assert ctx.sent == [
        "Live: 🏀 NBA — Contest\n"
        "• 🕒 2000-01-01\n"
        "• 🔗 DK: [1](<https://www.draftkings.com/contest/gamecenter/1#/>)\n"
        "• 📊 Sheet: n/a\n"
        "• ⭐ VIP: present"
    ]


@pytest.mark.asyncio
async def test_contests_links_dashboard_before_sheet(monkeypatch, ctx, as_context, make_settings, dummy_sport):
    monkeypatch.setattr(discord_bot, "_sport_choices", lambda: {"nba": dummy_sport})
    monkeypatch.setattr(
        discord_bot,
        "_fetch_live_contest",
        lambda sport_cls: (1, "Contest", None, None, "2000-01-01"),
    )
    monkeypatch.setattr(discord_bot, "_sheet_link", lambda _settings, _sport: "<https://sheet.example/nba>")
    monkeypatch.setattr(discord_bot, "_vip_presence_for_contest", lambda _dk_id: None)

    await discord_bot.contests(make_settings(dashboard_base_url="https://dashboard.example/"), as_context(ctx), "nba")

    assert ctx.sent[0].endswith(
        "• 📈 Dashboard: [NBA](<https://dashboard.example/live/nba>) | 📊 Sheet: [NBA](<https://sheet.example/nba>)"
    )


@pytest.mark.asyncio
async def test_contests_no_contest_found(monkeypatch, ctx, as_context, make_settings, dummy_sport):
    monkeypatch.setattr(discord_bot, "_sport_choices", lambda: {"nba": dummy_sport})
    monkeypatch.setattr(discord_bot, "_fetch_live_contest", lambda sport_cls: None)

    await discord_bot.contests(make_settings(), as_context(ctx), "nba")

    assert ctx.sent == ["No live contest found for NBA."]


def test_fetch_live_contest_closes_db(monkeypatch, dummy_sport):
    captured = {}

    class FakeDB:
        def __init__(self, *args, **kwargs):
            pass

        def get_live_contest(self, _name, _fee, _keyword):
            return (1, "Contest", None, None, "2000-01-01")

        def close(self):
            captured["closed"] = True

    monkeypatch.setattr(discord_bot, "ContestDatabase", FakeDB)

    assert discord_bot._fetch_live_contest(dummy_sport) == (
        1,
        "Contest",
        None,
        None,
        "2000-01-01",
    )
    assert captured.get("closed") is True


@pytest.mark.asyncio
async def test_contests_invalid_sport_config(monkeypatch, ctx, as_context, make_settings, dummy_sport):
    NamelessSport = type("NamelessSport", (dummy_sport,), {"name": None})

    monkeypatch.setattr(discord_bot, "_sport_choices", lambda: {"nba": NamelessSport})

    await discord_bot.contests(make_settings(), as_context(ctx), "nba")
    assert ctx.sent == ["Invalid sport configuration."]
