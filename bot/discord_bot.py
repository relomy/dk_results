import datetime
import logging
import logging.config
import os
import time
from pathlib import Path
from typing import Optional, Type, TypeAlias

import discord  # noqa: E402
import yaml
from discord.ext import commands

from classes.contestdatabase import ContestDatabase
from classes.sport import Sport

logging.config.fileConfig("logging.ini")
logger = logging.getLogger(__name__)

COMMAND_PREFIX = "!"
DB_PATH = os.getenv("CONTESTS_DB_PATH", "contests.db")
BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
START_TIME = time.time()
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")
SHEET_GIDS_FILE = os.getenv("SHEET_GIDS_FILE", "sheet_gids.yaml")
DISCORD_LOG_FILE = os.getenv("DISCORD_LOG_FILE")


SportType: TypeAlias = Type[Sport]


def _load_sheet_gid_map() -> dict[str, int]:
    if not SHEET_GIDS_FILE:
        logger.info("SHEET_GIDS_FILE not set; sheet links disabled.")
        return {}
    path = Path(SHEET_GIDS_FILE)
    if not path.is_file():
        logger.info("Sheet gid map not found at %s; sheet links disabled.", path)
        return {}
    try:
        data = yaml.safe_load(path.read_text()) or {}
    except Exception:
        logger.warning("Failed to load sheet gid map from %s", path)
        return {}
    if not isinstance(data, dict):
        logger.warning("Sheet gid map at %s did not contain a dict.", path)
        return {}
    gids: dict[str, int] = {}
    for key, value in data.items():
        if isinstance(key, str) and isinstance(value, int):
            gids[key] = value
        else:
            logger.debug("Skipping invalid gid entry %r -> %r", key, value)
    logger.info("Loaded %d sheet gid entries from %s", len(gids), path)
    return gids


SHEET_GID_MAP = _load_sheet_gid_map()

SPORT_EMOJI = {
    "CFB": "🏈",
    "GOLF": "⛳",
    "LOL": "🎮",
    "MLB": "⚾",
    "MMA": "🥊",
    "NAS": "🏎️",
    "NBA": "🏀",
    "NFL": "🏈",
    "NFLAfternoon": "🏈",
    "NFLShowdown": "🏈",
    "NHL": "🏒",
    "PGAMain": "⛳",
    "PGAShowdown": "⛳",
    "PGAWeekend": "⛳",
    "SOC": "⚽",
    "TEN": "🎾",
    "USFL": "🏈",
    "XFL": "🏈",
}


def _sheet_link(sheet_title: str) -> str | None:
    if not SPREADSHEET_ID:
        logger.debug("SPREADSHEET_ID not set; cannot build sheet link.")
        return None
    gid = SHEET_GID_MAP.get(sheet_title)
    if gid is None:
        logger.debug("No gid found for sheet title %s.", sheet_title)
        return None
    return f"<https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/edit#gid={gid}>"


def _sport_sheet_title(sport_cls: SportType) -> str:
    return getattr(sport_cls, "sheet_name", None) or sport_cls.name


def _sport_emoji(sport_name: str) -> str:
    return SPORT_EMOJI.get(sport_name, "🏟️")


def _configure_discord_log_file() -> None:
    log_path = (
        Path(DISCORD_LOG_FILE)
        if DISCORD_LOG_FILE
        else Path(__file__).resolve().parents[1] / "logs" / "discord_bot.log"
    )
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(log_path, mode="a")
        handler.setLevel(logging.DEBUG)
        formatter = logging.Formatter(
            "%(asctime)s %(name)s %(levelname)5s %(message)s", "%Y-%m-%d %H:%M:%S"
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.propagate = False
        logger.info("Discord bot file logging initialized at %s", log_path)
    except Exception:
        logger.exception("Failed to initialize Discord bot file logging.")


_configure_discord_log_file()


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


def _format_contest_row(row: tuple, sport_name: str, sheet_link: str | None) -> str:
    dk_id, name, _, _, start_date = row
    # Wrap URL in angle brackets to prevent Discord from embedding a preview.
    url = f"<https://www.draftkings.com/contest/gamecenter/{dk_id}#/>"
    return (
        f"sport={sport_name}: dk_id={dk_id}, name={name}, "
        f"start_date={start_date}, url={url}"
    )


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


def _format_time_until(start_date: str) -> str | None:
    try:
        start_dt = datetime.datetime.fromisoformat(start_date)
    except (TypeError, ValueError):
        return None
    now = datetime.datetime.now(start_dt.tzinfo)
    delta = start_dt - now
    if delta.total_seconds() <= 0:
        return None
    seconds = int(delta.total_seconds())
    minutes, sec = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    days, hours = divmod(hours, 24)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if not parts:
        parts.append(f"{sec}s")
    return f"⏳ {''.join(parts)}"


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

    sheet_link = _sheet_link(_sport_sheet_title(sport_choice))
    await ctx.send(_format_contest_row(contest, sport_choice.name, sheet_link))


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
        # Wrap URL in angle brackets to prevent Discord from embedding a preview.
        url = f"<https://www.draftkings.com/contest/gamecenter/{dk_id}#/>"
        sheet_link = _sheet_link(sport)
        sheet_part = f"📊 Sheet: {sheet_link}" if sheet_link else "📊 Sheet: n/a"
        lines.append(
            "\n".join(
                [
                    f"{_sport_emoji(sport)} {sport} — {name}",
                    f"• 🕒 {start_date}",
                    f"• 🔗 DK: {url}",
                    f"• {sheet_part}",
                ]
            )
        )

    await ctx.send("\n".join(lines))


@bot.command(name="upcoming")
async def upcoming(ctx: commands.Context):
    choices = _sport_choices()
    contest_db = ContestDatabase(DB_PATH, logger=logger)
    try:
        lines = []
        for sport_cls in choices.values():
            upcoming_any = contest_db.get_next_upcoming_contest_any(sport_cls.name)
            if not upcoming_any:
                continue

            upcoming_match = contest_db.get_next_upcoming_contest(
                sport_cls.name, sport_cls.sheet_min_entry_fee, sport_cls.keyword
            )
            dk_id, name, _, _, start_date = (
                upcoming_match if upcoming_match else upcoming_any
            )
            suffix = "" if upcoming_match else " (failed criteria)"
            relative = _format_time_until(str(start_date))
            relative_part = f" ({relative})" if relative else ""
            lines.append(
                f"{sport_cls.name}: name={name}, "
                f"start_date={start_date}{relative_part}{suffix}, "
                f"url=<https://www.draftkings.com/contest/gamecenter/{dk_id}#/>"
            )
    finally:
        contest_db.close()

    if not lines:
        return

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
        "!upcoming -> shows next upcoming contest per sport",
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
