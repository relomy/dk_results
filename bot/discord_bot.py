import logging
import logging.config
import os
import time
from typing import Optional, Type, TypeAlias

import discord  # noqa: E402
from discord.ext import commands

from classes.contestdatabase import ContestDatabase
from classes.sport import Sport

logging.config.fileConfig("logging.ini")
logger = logging.getLogger(__name__)

COMMAND_PREFIX = "!"
DB_PATH = os.getenv("CONTESTS_DB_PATH", "contests.db")
BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
START_TIME = time.time()


SportType: TypeAlias = Type[Sport]


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


def _sport_choices() -> dict[str, SportType]:
    choices: dict[str, SportType] = {}
    for sport in Sport.__subclasses__():
        name = getattr(sport, "name", None)
        if not isinstance(name, str) or not name:
            continue
        choices[name.lower()] = sport
    return choices


def _allowed_sports_label(choices: dict[str, SportType]) -> str:
    names: list[str] = [sport_cls.name for sport_cls in choices.values()]
    return ", ".join(sorted(names))


def _format_contest_row(row: tuple, sport_name: str) -> str:
    dk_id, name, _, _, start_date = row
    return f"{sport_name}: dk_id={dk_id}, name={name}, start_date={start_date}"


def _fetch_live_contest(sport_cls: SportType) -> Optional[tuple]:
    contest_db = ContestDatabase(DB_PATH, logger=logger)
    try:
        return contest_db.get_live_contest(
            sport_cls.name, sport_cls.sheet_min_entry_fee, sport_cls.keyword
        )
    finally:
        contest_db.close()


def _format_uptime(seconds: float) -> str:
    minutes, sec = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    days, hours = divmod(hours, 24)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    parts.append(f"{sec}s")
    return " ".join(parts)


def _system_uptime_seconds() -> Optional[float]:
    try:
        with open("/proc/uptime", "r") as f:
            first_field = f.read().split()[0]
            return float(first_field)
    except Exception:
        return None


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
    if isinstance(error, commands.CommandNotFound):
        # Ignore unknown commands so the bot only responds to expected prefixes.
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
            f"Unknown sport '{sport}'. Allowed options: "
            f"{_allowed_sports_label(choices)}"
        )
        return

    sport_choice = choices[sport_key]
    if not isinstance(getattr(sport_choice, "name", None), str):
        await ctx.send("Invalid sport configuration.")
        return

    contest = _fetch_live_contest(sport_choice)
    if not contest:
        await ctx.send(f"No live contest found for {sport_choice.name}.")
        return

    await ctx.send(_format_contest_row(contest, sport_choice.name))


@bot.command(name="live")
async def live(ctx: commands.Context):
    choices = _sport_choices()
    allowed_sports: list[str] = [sport_cls.name for sport_cls in choices.values()]

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


@bot.command(name="health")
async def health(ctx: commands.Context):
    uptime = _format_uptime(time.time() - START_TIME)
    sys_uptime_sec = _system_uptime_seconds()
    sys_uptime = _format_uptime(sys_uptime_sec) if sys_uptime_sec is not None else "n/a"
    await ctx.send(f"alive. bot uptime: {uptime}. host uptime: {sys_uptime}")


@bot.command(name="help")
async def help_command(ctx: commands.Context):
    choices = _sport_choices()
    allowed = _allowed_sports_label(choices)
    lines = [
        "!sankayadead -> responds 'ya man'",
        "!health -> shows bot uptime",
        (
            "!contests <sport> -> shows one live contest for that sport. "
            f"Sports: {allowed}"
        ),
        "!live -> shows all live contests across supported sports",
        "!sports -> lists supported sports",
    ]
    await ctx.send("\n".join(lines))


@bot.command(name="sports")
async def sports(ctx: commands.Context):
    choices = _sport_choices()
    allowed = _allowed_sports_label(choices)
    await ctx.send(f"Supported sports: {allowed}")


def main():
    if not BOT_TOKEN:
        raise RuntimeError(
            "DISCORD_BOT_TOKEN is not set. Set it before starting the Discord bot."
        )
    bot.run(BOT_TOKEN)


if __name__ == "__main__":
    main()
