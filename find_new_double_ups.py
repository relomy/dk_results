"""Find new double ups and print out a message when a new one is found."""

import argparse
import logging
import logging.config
from os import getenv
from typing import Type

from dfs_common.discord import WebhookSender
from dotenv import load_dotenv

import contests_state
from classes.contest import Contest
from classes.contestdatabase import ContestDatabase
from classes.sport import Sport
from discord_roles import DISCORD_ROLE_MAP
from lobby.double_ups import get_double_ups
from lobby.fetch import DEFAULT_HEADERS, LOBBY_URL_TEMPLATE, get_dk_lobby, requests_fetch_json
from lobby.formatting import format_discord_messages
from lobby.parsing import build_draft_group_start_map

LOGGING_CONFIG_FILE = "logging.ini"

logger = logging.getLogger(__name__)


def send_discord_notification(
    bot: WebhookSender | None, sport_name: str, message: str
) -> None:
    """Send a notification message to Discord for a specific sport."""
    if bot is None or sport_name not in DISCORD_ROLE_MAP:
        return
    emoji, role = DISCORD_ROLE_MAP[sport_name]
    bot.send_message(f"{emoji} {message} {role}")


def set_quiet_verbosity() -> None:
    """Set logger verbosity to INFO level."""
    logger.setLevel(logging.INFO)


def parse_args(choices: dict[str, Type[Sport]]) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-s",
        "--sport",
        choices=choices,
        required=True,
        help="Type of contest",
        nargs="+",
    )
    parser.add_argument("-q", "--quiet", action="store_true", help="Decrease verbosity")
    return parser.parse_args()


def process_sport(
    sport_name: str,
    choices: dict[str, Type[Sport]],
    db: ContestDatabase,
    bot: WebhookSender | None,
    *,
    lobby_cookies=None,
) -> None:
    """Process contests for a given sport and send Discord notifications."""
    if sport_name not in choices:
        raise Exception("Could not find matching Sport subclass")

    sport_obj = choices[sport_name]
    primary_sport = sport_obj.get_primary_sport()
    url = LOBBY_URL_TEMPLATE.format(sport=primary_sport)

    response_contests, draft_groups, response = get_dk_lobby(
        sport_obj,
        url,
        fetch_json=requests_fetch_json,
        headers=DEFAULT_HEADERS,
        cookies=lobby_cookies,
    )

    contests = [Contest(c, sport_obj.name) for c in response_contests]
    double_ups = get_double_ups(
        contests,
        draft_groups,
        min_entry_fee=sport_obj.dub_min_entry_fee,
        entries=sport_obj.dub_min_entries,
    )

    db.create_table()
    allowed_ids = set(draft_groups)
    start_map = build_draft_group_start_map(response.get("DraftGroups", []), allowed_ids)
    if start_map:
        updated_groups = db.sync_draft_group_start_dates(start_map)
        if updated_groups:
            logger.info("updated %d draft_group start_date values", updated_groups)
        else:
            logger.debug("no draft_group start_date updates needed")

    new_contest_ids = db.compare_contests(double_ups)
    if new_contest_ids:
        matching_contests = [c for c in contests if c.id in new_contest_ids]
        discord_message = format_discord_messages(matching_contests)
        logger.info(discord_message)
        contests_state.upsert_contests(matching_contests)
        send_discord_notification(bot, sport_obj.name, discord_message)


def _init_runtime() -> None:
    """Initialize runtime-only side effects for CLI execution."""
    load_dotenv()
    logging.config.fileConfig(LOGGING_CONFIG_FILE)


def _load_lobby_cookies():
    from classes.cookieservice import get_dk_cookies

    _, cookies = get_dk_cookies()
    return cookies


def main() -> None:
    """Main function to find new double ups and send notifications."""
    _init_runtime()

    sportz: list[Type[Sport]] = Sport.__subclasses__()
    choices: dict[str, Type[Sport]] = {sport.name: sport for sport in sportz}

    webhook = getenv("DISCORD_WEBHOOK")
    if not webhook:
        logger.warning("DISCORD_WEBHOOK is not set. Discord notifications disabled.")
        bot = None
    else:
        bot = WebhookSender(webhook)

    args = parse_args(choices)
    if args.quiet:
        set_quiet_verbosity()

    db_path = str(contests_state.contests_db_path())
    contests_state.ensure_schema()
    lobby_cookies = _load_lobby_cookies()

    db = ContestDatabase(db_path)
    try:
        for sport_name in args.sport:
            process_sport(sport_name, choices, db, bot, lobby_cookies=lobby_cookies)
    finally:
        db.close()


if __name__ == "__main__":
    main()
