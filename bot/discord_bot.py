import logging
import logging.config
import os
import sys
from pathlib import Path
from typing import Optional

# Ensure we import the discord library, not the local legacy webhook module.
CURRENT_DIR = Path(__file__).resolve().parent
if sys.path and sys.path[0] == str(CURRENT_DIR):
    sys.path.pop(0)
    sys.path.insert(0, str(CURRENT_DIR.parent))

import discord
from discord.ext import commands

from classes.contestdatabase import ContestDatabase
from classes.sport import Sport

logging.config.fileConfig("logging.ini")
logger = logging.getLogger(__name__)

COMMAND_PREFIX = "!"
DB_PATH = os.getenv("CONTESTS_DB_PATH", "contests.db")
BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")


def _channel_id_from_env() -> Optional[int]:
    raw_channel_id = os.getenv("DISCORD_CHANNEL_ID")
    if not raw_channel_id:
        return None
    try:
        return int(raw_channel_id)
    except ValueError:
        logger.warning("DISCORD_CHANNEL_ID is not a valid integer: %s", raw_channel_id)
        return None


ALLOWED_CHANNEL_ID = _channel_id_from_env()

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix=COMMAND_PREFIX, intents=intents, help_command=None)


def _sport_choices() -> dict[str, type]:
    sportz = Sport.__subclasses__()
    return {
        sport.name.lower(): sport for sport in sportz if getattr(sport, "name", None)
    }


def _allowed_sports_label(choices: dict[str, type]) -> str:
    return ", ".join(sorted({sport_cls.name for sport_cls in choices.values()}))


def _format_contest_row(row: tuple, sport_name: str) -> str:
    dk_id, name, _, _, start_date = row
    return f"{sport_name}: dk_id={dk_id}, name={name}, start_date={start_date}"


def _fetch_live_contest(sport_cls: type) -> Optional[tuple]:
    contest_db = ContestDatabase(DB_PATH, logger=logger)
    try:
        return contest_db.get_live_contest(
            sport_cls.name, sport_cls.sheet_min_entry_fee, sport_cls.keyword
        )
    finally:
        contest_db.close()


@bot.check
async def limit_to_channel(ctx: commands.Context) -> bool:
    if ALLOWED_CHANNEL_ID is None:
        return True
    channel = getattr(ctx, "channel", None)
    return bool(channel and channel.id == ALLOWED_CHANNEL_ID)


@bot.event
async def on_ready():
    logger.info("Discord bot logged in as %s", bot.user)


@bot.event
async def on_command_error(ctx: commands.Context, error: Exception):
    if isinstance(error, commands.CheckFailure):
        # Silently ignore commands from other channels.
        return
    logger.error("Command error: %s", error)
    await ctx.send("Something went wrong running that command.")


@bot.command(name="sankayadead")
async def sankayadead(ctx: commands.Context):
    await ctx.send("ya man")


@bot.command(name="contests")
async def contests(ctx: commands.Context, sport: Optional[str] = None):
    choices = _sport_choices()
    if not sport:
        await ctx.send(f"Pick a sport: {_allowed_sports_label(choices)}")
        return

    sport_key = sport.lower()
    if sport_key not in choices:
        await ctx.send(
            f"Unknown sport '{sport}'. Allowed options: {_allowed_sports_label(choices)}"
        )
        return

    contest = _fetch_live_contest(choices[sport_key])
    if not contest:
        await ctx.send(f"No live contest found for {choices[sport_key].name}.")
        return

    await ctx.send(_format_contest_row(contest, choices[sport_key].name))


@bot.command(name="live")
async def live(ctx: commands.Context):
    choices = _sport_choices()
    allowed_sports = [sport_cls.name for sport_cls in choices.values()]

    contest_db = ContestDatabase(DB_PATH, logger=logger)
    try:
        rows = contest_db.get_live_contests(sports=allowed_sports)
    finally:
        contest_db.close()

    if not rows:
        await ctx.send("No live contests found.")
        return

    lines = []
    for dk_id, name, _, _, start_date, sport in rows:
        lines.append(f"{sport}: dk_id={dk_id}, name={name}, start_date={start_date}")

    await ctx.send("\n".join(lines))


def main():
    if not BOT_TOKEN:
        raise RuntimeError(
            "DISCORD_BOT_TOKEN is not set. Set it before starting the Discord bot."
        )
    bot.run(BOT_TOKEN)


if __name__ == "__main__":
    main()
