"""Find new double ups and print out a message when a new one is found."""

import argparse
import datetime
import logging
import logging.config
import sys
from os import getenv
from typing import Optional, Type

import requests
from dotenv import load_dotenv

from bot.webhook import DiscordWebhook as Discord
from classes.contest import Contest
from classes.contestdatabase import ContestDatabase
from classes.cookieservice import get_dk_cookies
from classes.sport import Sport
from discord_roles import DISCORD_ROLE_MAP

load_dotenv()

# Centralized constants
LOBBY_URL_TEMPLATE = "https://www.draftkings.com/lobby/getcontests?sport={sport}"
DB_FILE = "contests.db"
LOGGING_CONFIG_FILE = "logging.ini"
DEFAULT_MIN_ENTRY_FEE = 5
DEFAULT_MAX_ENTRY_FEE = 50
DEFAULT_MIN_ENTRIES = 125

# load the logging configuration
logging.config.fileConfig(LOGGING_CONFIG_FILE)

logger = logging.getLogger(__name__)

cookie_dict, jar = get_dk_cookies()
COOKIES = jar
HEADERS = {
    "Accept": "*/*",
    "Accept-Encoding": "gzip, deflate, sdch",
    "Accept-Language": "en-US,en;q=0.8",
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    # 'Cookie': os.environ['DK_AUTH_COOKIES'],
    "Host": "www.draftkings.com",
    "Pragma": "no-cache",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_10_5) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/48.0.2564.97 Safari/537.36"
    ),
    "X-Requested-With": "XMLHttpRequest",
}


def send_discord_notification(
    bot: Discord | None, sport_name: str, message: str
) -> None:
    """
    Send a notification message to Discord for a specific sport.

    Args:
        bot (Discord): Discord bot instance.
        sport_name (str): Name of the sport.
        message (str): Message to send.
    """
    if bot is None or sport_name not in DISCORD_ROLE_MAP:
        return
    emoji, role = DISCORD_ROLE_MAP[sport_name]
    bot.send_message(f"{emoji} {message} {role}")


def get_dk_lobby(sport: Type[Sport], url: str) -> tuple[list, list, dict]:
    """
    Get contests and draft groups from the DraftKings lobby.

    Args:
        sport (Sport): Sport object.
        url (str): URL to fetch contests.

    Returns:
        tuple[list, list]: List of contests and list of draft groups.
    """
    # set cookies based on Chrome session
    # logger.debug(url)

    response = requests.get(url, headers=HEADERS, cookies=COOKIES).json()

    contests = get_contests_from_response(response)
    draft_groups = get_draft_groups_from_response(response, sport)

    return contests, draft_groups, response


def get_contests_from_response(response: dict | list) -> list:
    """
    Extract contests from the DraftKings lobby response.

    Args:
        response (dict | list): Response from DraftKings API.

    Returns:
        list: List of contests.
    """
    if isinstance(response, list):
        response_contests = response
    elif "Contests" in response:
        response_contests = response["Contests"]
    else:
        logger.error("response isn't a dict or a list??? exiting")
        sys.exit()

    return response_contests


def log_draft_group_event(
    action: str,
    sport_obj: Sport | Type[Sport],
    start_date: datetime.datetime,
    draft_group_id: int,
    tag: str,
    suffix: str | None,
    contest_type_id: int,
    game_type_id: int,
    *,
    level: int = logging.INFO,
    reason: str | None = None,
) -> None:
    """
    Log a draft group action with consistent formatting.

    Args:
        action (str): Description of the action (e.g., "Append", "Skip").
        sport_obj (Sport): Sport object.
        start_date (datetime.datetime): Draft group start time.
        draft_group_id (int): Draft group ID.
        tag (str): Draft group tag.
        suffix (str | None): Draft group suffix.
        contest_type_id (int): Contest type ID.
        level (int, optional): Logging level. Defaults to logging.INFO.
        reason (str | None, optional): Additional context for the action.
    """
    message = "[%4s] %s: start date: [%s] dg/tag/suffix/typid/gameid: [%d]/[%s]/[%s]/[%d]/[%d]"
    args: tuple = (
        sport_obj.name,
        action,
        start_date,
        draft_group_id,
        tag,
        suffix,
        contest_type_id,
        game_type_id,
    )
    if reason:
        message += " reason: %s"
        args = args + (reason,)
    logger.log(level, message, *args)


def get_draft_groups_from_response(response: dict, sport_obj: Type[Sport]) -> list:
    """
    Extract draft group IDs from the DraftKings lobby response.

    Args:
        response (dict): Response from DraftKings API.
        sport_obj (Sport): Sport object.

    Returns:
        list: List of draft group IDs.
    """
    response_draft_groups = []
    skipped_dg_suffixes = []
    suffix_patterns = sport_obj.get_suffix_patterns()
    allow_suffixless = sport_obj.allow_suffixless_draft_groups
    is_nfl_showdown = sport_obj.name == "NFLShowdown"
    showdown_entries = []

    for draft_group in response["DraftGroups"]:
        sport = draft_group["Sport"]
        tag = draft_group["DraftGroupTag"]
        suffix = draft_group["ContestStartTimeSuffix"]
        draft_group_id = draft_group["DraftGroupId"]
        start_date_est = draft_group["StartDateEst"]
        contest_type_id = draft_group["ContestTypeId"]
        game_type_id = draft_group["GameTypeId"]
        game_type = draft_group["GameType"]

        if suffix is not None:
            suffix = suffix.strip() or None

        # Only care about featured draftgroups and those with no suffix or special cases
        if tag != "Featured":
            if suffix:
                skipped_dg_suffixes.append(suffix)
            continue

        dt_start_date = datetime.datetime.fromisoformat(start_date_est[:-8])

        if (
            sport_obj.contest_restraint_game_type_id is not None
            and game_type_id != sport_obj.contest_restraint_game_type_id
        ):
            log_draft_group_event(
                "Skip",
                sport_obj,
                dt_start_date,
                draft_group_id,
                tag,
                suffix,
                contest_type_id,
                game_type_id,
                level=logging.DEBUG,
                reason=(
                    "game type constraint "
                    f"(!={sport_obj.contest_restraint_game_type_id}, got {game_type_id})"
                ),
            )
            continue

        if suffix is None:
            if not allow_suffixless:
                log_draft_group_event(
                    "Skip",
                    sport_obj,
                    dt_start_date,
                    draft_group_id,
                    tag,
                    suffix,
                    contest_type_id,
                    game_type_id,
                    level=logging.DEBUG,
                    reason="suffix required",
                )
                skipped_dg_suffixes.append("<<none>>")
                continue
            log_draft_group_event(
                "Append",
                sport_obj,
                dt_start_date,
                draft_group_id,
                tag,
                suffix,
                contest_type_id,
                game_type_id,
            )
            response_draft_groups.append(draft_group_id)
            continue

        # If sport_obj has suffixes, use regex matching
        matches_suffix = False
        if suffix_patterns:
            matches_suffix = any(pattern.search(suffix) for pattern in suffix_patterns)

        if not matches_suffix:
            if suffix:
                skipped_dg_suffixes.append(suffix)
            log_draft_group_event(
                "Skip",
                sport_obj,
                dt_start_date,
                draft_group_id,
                tag,
                suffix,
                contest_type_id,
                game_type_id,
                level=logging.DEBUG,
                reason="suffix mismatch",
            )
            continue

        if (
            sport_obj.contest_restraint_time
            and dt_start_date.time() < sport_obj.contest_restraint_time
        ):
            log_draft_group_event(
                "Skip",
                sport_obj,
                dt_start_date,
                draft_group_id,
                tag,
                suffix,
                contest_type_id,
                game_type_id,
                level=logging.DEBUG,
                reason=f"time constraint (<{sport_obj.contest_restraint_time})",
            )
            continue

        if is_nfl_showdown:
            start_key = dt_start_date.replace(second=0, microsecond=0)
            showdown_entries.append(
                (
                    start_key,
                    draft_group_id,
                    tag,
                    suffix,
                    contest_type_id,
                    game_type_id,
                    dt_start_date,
                )
            )
            continue

        log_draft_group_event(
            "Append",
            sport_obj,
            dt_start_date,
            draft_group_id,
            tag,
            suffix,
            contest_type_id,
            game_type_id,
        )
        response_draft_groups.append(draft_group_id)

    if skipped_dg_suffixes:
        logger.debug(
            "[%4s] Skipped suffixes [%s]",
            sport_obj.name,
            ", ".join(skipped_dg_suffixes),
        )

    if is_nfl_showdown and showdown_entries:
        showdown_counts = {}
        for start_key, *_ in showdown_entries:
            showdown_counts[start_key] = showdown_counts.get(start_key, 0) + 1

        for (
            start_key,
            draft_group_id,
            tag,
            suffix,
            contest_type_id,
            game_type_id,
            dt_start_date,
        ) in showdown_entries:
            if showdown_counts[start_key] == 1:
                log_draft_group_event(
                    "Append",
                    sport_obj,
                    dt_start_date,
                    draft_group_id,
                    tag,
                    suffix,
                    contest_type_id,
                    game_type_id,
                )
                response_draft_groups.append(draft_group_id)
            else:
                log_draft_group_event(
                    "Skip",
                    sport_obj,
                    dt_start_date,
                    draft_group_id,
                    tag,
                    suffix,
                    contest_type_id,
                    game_type_id,
                    level=logging.DEBUG,
                    reason="multiple NFLShowdown draft groups at same start time",
                )

    return response_draft_groups


def build_draft_group_start_map(
    draft_groups: list[dict], allowed_ids: set[int]
) -> dict[int, datetime.datetime]:
    """
    Build a draft_group -> start datetime map for allowed draft groups.

    Args:
        draft_groups (list[dict]): Draft groups from the lobby response.
        allowed_ids (set[int]): Draft group IDs to include.

    Returns:
        dict[int, datetime.datetime]: Draft group IDs mapped to start datetimes.
    """
    if not draft_groups or not allowed_ids:
        return {}

    start_map: dict[int, datetime.datetime] = {}
    for draft_group in draft_groups:
        draft_group_id = draft_group.get("DraftGroupId")
        if draft_group_id is None or draft_group_id not in allowed_ids:
            continue
        start_date_est = draft_group.get("StartDateEst")
        if not start_date_est:
            continue
        try:
            start_map[draft_group_id] = datetime.datetime.fromisoformat(
                start_date_est[:-8]
            )
        except (TypeError, ValueError):
            logger.debug(
                "invalid StartDateEst for dg_id=%s: %s",
                draft_group_id,
                start_date_est,
            )
    return start_map


def valid_date(date_string: str) -> datetime.datetime:
    """
    Validate and parse a date string in YYYY-MM-DD format.

    Args:
        date_string (str): Date string to validate.

    Returns:
        datetime.datetime: Parsed datetime object.

    Raises:
        argparse.ArgumentTypeError: If date_string is not valid.
    """
    try:
        return datetime.datetime.strptime(date_string, "%Y-%m-%d")
    except ValueError:
        msg = "Not a valid date: '{0}'.".format(date_string)
        raise argparse.ArgumentTypeError(msg)


def get_stats(contests: list[Contest]) -> dict:
    """
    Get statistics for a list of Contest objects.

    Args:
        contests (list[Contest]): List of Contest objects.

    Returns:
        dict: Statistics grouped by start date.
    """
    stats = {}
    for contest in contests:
        start_date = contest.start_dt.strftime("%Y-%m-%d")

        # initialize stats[start_date] if it doesn't exist
        if start_date not in stats:
            stats[start_date] = {"count": 0}

        stats[start_date]["count"] += 1

        # keep track of single-entry double-ups
        if (
            contest.max_entry_count == 1
            and contest.is_guaranteed
            and contest.is_double_up
        ):
            # initialize stats[start_date]["dubs"] if it doesn't exist
            if "dubs" not in stats[start_date]:
                stats[start_date]["dubs"] = {contest.entry_fee: 0}

            # initialize stats[start_date]["dubs"][c.entry_fee] if it doesn't exist
            if contest.entry_fee not in stats[start_date]["dubs"]:
                stats[start_date]["dubs"][contest.entry_fee] = 0

            stats[start_date]["dubs"][contest.entry_fee] += 1

    return stats


def get_double_ups(
    contests: list[Contest],
    draft_groups: list,
    min_entry_fee: int = 5,
    max_entry_fee: int = 50,
    entries: int = 125,
) -> list[Contest]:
    """
    Find contests matching double-up criteria.

    Args:
        contests (list[Contest]): List of Contest objects.
        draft_groups (list): List of draft group IDs.
        min_entry_fee (int): Minimum entry fee.
        max_entry_fee (int): Maximum entry fee.
        entries (int): Minimum number of entries.

    Returns:
        list[Contest]: List of contests matching criteria.
    """
    criteria = {
        "draft_groups": draft_groups,
        "min_entry_fee": min_entry_fee,
        "max_entry_fee": max_entry_fee,
        "entries": entries,
    }
    return [
        contest for contest in contests if contest_meets_criteria(contest, criteria)
    ]


def contest_meets_criteria(contest: Contest, criteria: dict) -> bool:
    """
    Check if a contest meets the specified criteria.

    Args:
        contest (Contest): Contest object.
        criteria (dict): Criteria dictionary.

    Returns:
        bool: True if contest meets criteria, False otherwise.
    """
    return (
        contest.entries >= criteria["entries"]
        and contest.draft_group in criteria["draft_groups"]
        and contest.entry_fee >= criteria["min_entry_fee"]
        and contest.entry_fee <= criteria["max_entry_fee"]
        and contest.max_entry_count == 1
        and contest.is_guaranteed
        and contest.is_double_up
    )


def get_salary_date(draft_group: dict) -> datetime.date:
    """
    Get the salary date from a draft group.

    Args:
        draft_group (dict): Draft group dictionary.

    Returns:
        datetime.date: Salary date.
    """
    return datetime.datetime.strptime(
        draft_group["StartDateEst"].split("T")[0], "%Y-%m-%d"
    ).date()


def is_time_between(
    begin_time: datetime.time,
    end_time: datetime.time,
    check_time: Optional[datetime.time] = None,
) -> bool:
    """
    Check if a time is between two times.

    Args:
        begin_time (datetime.time): Start time.
        end_time (datetime.time): End time.
        check_time (datetime.time, optional): Time to check. Defaults to current UTC time.

    Returns:
        bool: True if check_time is between begin_time and end_time.
    """
    # If check time is not given, default to current UTC time
    check_time = check_time or datetime.datetime.now(datetime.timezone.utc).time()
    if begin_time < end_time:
        # return check_time >= begin_time and check_time <= end_time
        return begin_time <= check_time <= end_time

    # crosses midnight
    return check_time >= begin_time or check_time <= end_time


def set_quiet_verbosity() -> None:
    """
    Set logger verbosity to INFO level.
    """
    logger.setLevel(logging.INFO)


def format_discord_messages(contests: list["Contest"]) -> str:
    """
    Format a list of Contest objects into Discord notification messages.

    Args:
        contests (list[Contest]): List of Contest objects.

    Returns:
        str: Formatted message string.
    """
    return "\n".join(
        f"New dub found! [{c.start_dt:%Y-%m-%d}] Name: {c.name} ID: {c.id} Entry Fee: {c.entry_fee} Entries: {c.entries}"
        for c in contests
    )


def parse_args(choices: dict[str, Type[Sport]]) -> argparse.Namespace:
    """
    Parse command-line arguments.

    Args:
        choices (dict[str, type]): Dictionary of available sport choices.

    Returns:
        argparse.Namespace: Parsed arguments.
    """
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
    bot: Discord | None,
) -> None:
    """
    Process contests for a given sport, compare with database, and send Discord notifications.

    Args:
        sport_name (str): Name of the sport.
        choices (dict[str, type]): Dictionary mapping sport names to Sport subclasses.
        db (ContestDatabase): Contest database instance.
        bot (Discord | None): Discord bot instance or None.
    """
    if sport_name not in choices:
        raise Exception("Could not find matching Sport subclass")
    sport_obj = choices[sport_name]
    primary_sport = sport_obj.get_primary_sport()
    url = LOBBY_URL_TEMPLATE.format(sport=primary_sport)
    response_contests, draft_groups, response = get_dk_lobby(sport_obj, url)
    contests = [Contest(c, sport_obj.name) for c in response_contests]
    double_ups = get_double_ups(
        contests,
        draft_groups,
        min_entry_fee=sport_obj.dub_min_entry_fee,
        entries=sport_obj.dub_min_entries,
    )
    db.create_table()
    allowed_ids = set(draft_groups)
    start_map = build_draft_group_start_map(
        response.get("DraftGroups", []), allowed_ids
    )
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
        db.insert_contests(matching_contests)
        send_discord_notification(bot, sport_obj.name, discord_message)


def main() -> None:
    """
    Main function to find new double ups and send notifications.

    Parses arguments, fetches contests, compares with database, and sends notifications.
    """
    sportz: list[Type[Sport]] = Sport.__subclasses__()
    choices: dict[str, Type[Sport]] = {sport.name: sport for sport in sportz}

    webhook = getenv("DISCORD_WEBHOOK")
    if not webhook:
        logger.warning("DISCORD_WEBHOOK is not set. Discord notifications disabled.")
        bot = None
    else:
        bot = Discord(webhook)

    # parse arguments
    args = parse_args(choices)

    if args.quiet:
        set_quiet_verbosity()

    # create connection to database file
    db = ContestDatabase(DB_FILE)
    try:
        for sport_name in args.sport:
            process_sport(sport_name, choices, db, bot)
    finally:
        db.close()


if __name__ == "__main__":
    main()
