"""Tests for the bot's time and uptime formatting helpers."""

import datetime

import pytest

from dk_results.bot import discord_bot


def test_format_time_until_future():
    now = datetime.datetime.now().replace(microsecond=0)
    future = now + datetime.timedelta(minutes=13, seconds=30)
    past = now - datetime.timedelta(minutes=1)

    assert discord_bot._format_time_until(future.isoformat(sep=" ")) == "⏳ 13m"
    assert discord_bot._format_time_until(past.isoformat(sep=" ")) is None


def test_format_time_since_past():
    now = datetime.datetime.now().replace(microsecond=0)
    past = now - datetime.timedelta(hours=2, minutes=13)
    future = now + datetime.timedelta(minutes=1)

    assert discord_bot._format_time_since(past.isoformat(sep=" ")) == "started 2h13m ago"
    assert discord_bot._format_time_since(future.isoformat(sep=" ")) is None


def test_format_time_since_invalid():
    assert discord_bot._format_time_since("not-a-date") is None


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
