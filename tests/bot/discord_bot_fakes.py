"""Shared fakes for the discord_bot command tests."""

import os
import types
from typing import cast

from discord.ext import commands

os.environ.setdefault("DFS_STATE_DIR", "/tmp")


class FakeCtx:
    def __init__(self):
        self.sent = []
        self.channel = types.SimpleNamespace(id=None)

    async def send(self, message: str):
        self.sent.append(message)


def _ctx(ctx: FakeCtx) -> commands.Context:
    return cast(commands.Context, ctx)


class DummySport:
    name = "NBA"
    sheet_min_entry_fee = 5
    keyword = "%"


class DummySportTwo:
    name = "NFL"
    sheet_min_entry_fee = 5
    keyword = "%"
