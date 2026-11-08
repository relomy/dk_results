"""Fixtures for the discord_bot command tests: a recording Context, RuntimeSettings and dummy sports."""

import dataclasses
import os
import types
from collections.abc import Callable
from typing import cast

import pytest
from discord.ext import commands

from dk_results.config import RuntimeSettings
from dk_results.domain.sport import Sport

os.environ.setdefault("DFS_STATE_DIR", "/tmp")


class FakeCtx:
    def __init__(self):
        self.sent: list[str] = []
        self.channel = types.SimpleNamespace(id=None)

    async def send(self, message: str):
        self.sent.append(message)


class DummySport(Sport):
    name = "NBA"
    sheet_min_entry_fee = 5
    keyword = "%"


class DummySportTwo(Sport):
    name = "NFL"
    sheet_min_entry_fee = 5
    keyword = "%"


@pytest.fixture
def ctx() -> FakeCtx:
    """A command Context that records what it sends."""
    return FakeCtx()


@pytest.fixture
def make_ctx() -> type[FakeCtx]:
    """``make_ctx()``: another Context, for a test that needs more than one."""
    return FakeCtx


@pytest.fixture
def as_context() -> Callable[[FakeCtx], commands.Context]:
    """``as_context(ctx)``: the fake, typed as the Context the bot's commands take."""

    def convert(ctx: FakeCtx) -> commands.Context:
        return cast(commands.Context, ctx)

    return convert


@pytest.fixture
def make_settings() -> Callable[..., RuntimeSettings]:
    def build(**overrides: object) -> RuntimeSettings:
        """RuntimeSettings with nothing configured, then ``overrides`` applied."""
        base = RuntimeSettings(
            spreadsheet_id=None,
            dfs_state_dir=None,
            sheet_gids_file="sheet_gids.yaml",
            sheet_gid_map={},
            discord_notifications_enabled=True,
            contest_warning_minutes=25,
            warning_schedule_file="contest_warning_schedules.yaml",
            warning_schedules={"default": [25]},
            default_warning_schedule=[25],
            dashboard_base_url=None,
            bot_token=None,
            discord_log_file=None,
            discord_channel_id=None,
        )
        return dataclasses.replace(base, **overrides)

    return build


@pytest.fixture
def dummy_sport() -> type[Sport]:
    return DummySport


@pytest.fixture
def dummy_sport_two() -> type[Sport]:
    return DummySportTwo
