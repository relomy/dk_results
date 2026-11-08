"""Shared fakes for the discord_bot command tests."""

import dataclasses
import os
import types
from typing import cast

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


def _settings(**overrides: object) -> RuntimeSettings:
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


def _ctx(ctx: FakeCtx) -> commands.Context:
    return cast(commands.Context, ctx)


class DummySport(Sport):
    name = "NBA"
    sheet_min_entry_fee = 5
    keyword = "%"


class DummySportTwo(Sport):
    name = "NFL"
    sheet_min_entry_fee = 5
    keyword = "%"
