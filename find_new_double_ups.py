"""Find new double ups and print out a message when a new one is found."""

import argparse
import datetime
import logging
import logging.config
import re
import sqlite3
import sys
from os import getenv

import requests
from dotenv import load_dotenv

from bot.discord import Discord
from classes.contest import Contest
from classes.cookieservice import get_dk_cookies
from classes.sport import Sport
from discord_roles import DISCORD_ROLE_MAP

load_dotenv()

# load the logging configuration
logging.config.fileConfig("logging.ini")

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


def send_discord_notification(bot: Discord, sport_name: str, message: str) -> None:
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


def get_dk_lobby(sport: Sport, url: str) -> tuple[list, list]:
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

    return contests, draft_groups


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


def get_draft_groups_from_response(response: dict, sport_obj: Sport) -> list:
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
    for draft_group in response["DraftGroups"]:
        # dg['StartDateEst'] should be mostly the same for draft groups, (might
        # not be the same for the rare long-running contest) and should be the
        # date we're looking for (game date in US time).
        # date = get_salary_date(response["DraftGroups"])
        # date = get_salary_date(draft_group)
        # contest_type_id = draft_group["ContestTypeId"]
        sport = draft_group["Sport"]
        tag = draft_group["DraftGroupTag"]
        suffix = draft_group["ContestStartTimeSuffix"]
        draft_group_id = draft_group["DraftGroupId"]
        start_date_est = draft_group["StartDateEst"]
        contest_type_id = draft_group["ContestTypeId"]

        if suffix is not None:
            suffix = suffix.strip()

        suffix_list = [
            "(PGA)",
            "(PGA TOUR)",
            "(Weekend PGA TOUR)",
            "(AUS)",  # TEN
            "(LCS)",  # LOL
            "(LEC)",
            "(LPL)",
            "(Cup)",  # NAS
            "(Preseason)",  # NFL preseason
        ]

        # only care about featured draftgroups and those with no suffix
        # some special cases in list above
        if tag == "Featured":
            # python won't convert the DK state time because of the milliseconds
            dt_start_date = datetime.datetime.fromisoformat(start_date_est[:-8])
            if sport_obj.suffixes:
                suffix_patterns = [
                    re.compile(pattern) for pattern in sport_obj.suffixes
                ]

                if suffix is not None and any(
                    pattern.search(suffix) for pattern in suffix_patterns
                ):
                    if (
                        sport_obj.contest_restraint_time
                        and dt_start_date.time() < sport_obj.contest_restraint_time
                    ):
                        logger.debug(
                            "[%4s] Skipping [time constraint] (<%s): start date: [%s] dg/tag/suffix/typid: [%d]/[%s]/[%s]/[%d]",
                            sport_obj.name,
                            sport_obj.contest_restraint_time,
                            dt_start_date,
                            draft_group_id,
                            tag,
                            suffix,
                            contest_type_id,
                        )
                        continue

                    logger.info(
                        "[%4s] Append: start date: [%s] dg/tag/suffix/typid: [%d]/[%s]/[%s]/[%d]",
                        sport_obj.name,
                        dt_start_date,
                        draft_group_id,
                        tag,
                        suffix,
                        contest_type_id,
                    )
                    response_draft_groups.append(draft_group_id)
                    continue
            else:
                if suffix is None or suffix.strip() in suffix_list:
                    logger.info(
                        "[%4s] Append: start date: [%s] dg/tag/suffix/typid: [%d]/[%s]/[%s]/[%d]",
                        sport_obj.name,
                        dt_start_date,
                        draft_group_id,
                        tag,
                        suffix,
                        contest_type_id,
                    )
                    response_draft_groups.append(draft_group_id)
                    continue

        if suffix:
            skipped_dg_suffixes.append(suffix)

    if skipped_dg_suffixes:
        logger.debug(
            "[%4s] Skipped suffixes [%s]",
            sport_obj.name,
            ", ".join(skipped_dg_suffixes),
        )

    return response_draft_groups


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
    contest_list = []
    for contest in contests:
        # skip contests not for today
        # if contest.start_dt.date() != datetime.datetime.today().date():
        #     continue
        if contest_meets_criteria(contest, criteria):
            contest_list.append(contest)

    return contest_list


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


def create_connection(db_file: str) -> None:
    """
    Create a database connection to a SQLite database.

    Args:
        db_file (str): Path to the database file.
    """
    conn = None
    try:
        conn = sqlite3.connect(db_file)
        logger.debug(sqlite3.sqlite_version)
    except sqlite3.Error as err:
        logger.error(err)
    finally:
        if conn:
            conn.close()


def db_create_table(conn: sqlite3.Connection) -> None:
    """
    Create the contests table in the database if it does not exist.

    Args:
        conn (sqlite3.Connection): SQLite database connection.
    """
    cur = conn.cursor()

    sql = """
    CREATE TABLE IF NOT EXISTS "contests" (
        "dk_id" INTEGER,
        "sport" varchar(10) NOT NULL,
        "name"  varchar(50) NOT NULL,
        "start_date"    datetime NOT NULL,
        "draft_group"   INTEGER NOT NULL,
        "total_prizes"  INTEGER NOT NULL,
        "entries"       INTEGER NOT NULL,
        "positions_paid"        INTEGER,
        "entry_fee"     INTEGER NOT NULL,
        "entry_count"   INTEGER NOT NULL,
        "max_entry_count"       INTEGER NOT NULL,
        "completed"     INTEGER NOT NULL DEFAULT 0,
        "status"        TEXT,
        PRIMARY KEY("dk_id")
    );
    """

    cur.execute(sql)


def db_compare_contests(
    conn: sqlite3.Connection, contests: list[Contest]
) -> list[int] | None:
    """
    Compare contest IDs with those in the database.

    Args:
        conn (sqlite3.Connection): SQLite database connection.
        contests (list[Contest]): List of Contest objects.

    Returns:
        list[int] | None: List of new contest IDs not in the database.
    """
    # get cursor
    cur = conn.cursor()

    # get all rows with matching dk_ids
    dk_ids = [c.id for c in contests]

    try:
        # execute SQL command
        sql = "SELECT dk_id FROM contests WHERE dk_id IN ({0})".format(
            ", ".join("?" for _ in dk_ids)
        )
        cur.execute(sql, dk_ids)

        # fetch rows
        rows = cur.fetchall()

        # return None if nothing found
        # if not rows:
        #     print("All contest IDs are accounted for in database")
        #     return None

        # if there are rows, remove found id from ids list
        if rows and len(rows) >= 1:
            for row in rows:
                if row[0] in dk_ids:
                    dk_ids.remove(row[0])

        return dk_ids

    except sqlite3.Error as err:
        logger.error("sqlite error: %s", err.args[0])


def db_insert_contests(conn: sqlite3.Connection, contests: list[Contest]) -> int | None:
    """
    Insert contests into the database.

    Args:
        conn (sqlite3.Connection): SQLite database connection.
        contests (list[Contest]): List of Contest objects.

    Returns:
        int | None: Last row ID inserted.
    """
    # create SQL command
    columns = [
        "sport",
        "dk_id",
        "name",
        "start_date",
        "draft_group",
        "total_prizes",
        "entries",
        "entry_fee",
        "entry_count",
        "max_entry_count",
    ]
    sql = "INSERT INTO contests ({}) VALUES ({});".format(
        ", ".join(columns), ", ".join("?" for _ in columns)
    )

    cur = conn.cursor()

    # create tuple for SQL command
    for contest in contests:
        tpl_contest = (
            contest.sport,
            contest.id,
            contest.name,
            contest.start_dt,
            contest.draft_group,
            contest.total_prizes,
            contest.entries,
            contest.entry_fee,
            contest.entry_count,
            contest.max_entry_count,
        )

        try:
            # execute SQL command
            cur.execute(sql, tpl_contest)
        except sqlite3.Error as err:
            logger.error("sqlite error: %s", err.args[0])

    # commit database
    conn.commit()

    return cur.lastrowid


def is_time_between(
    begin_time: datetime.time, end_time: datetime.time, check_time: datetime.time = None
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
    check_time = check_time or datetime.datetime.utcnow().time()
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


def parse_args(choices: dict) -> argparse.Namespace:
    """
    Parse command-line arguments.

    Args:
        choices (dict): Dictionary of available sport choices.

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


def main() -> None:
    """
    Main function to find new double ups and send notifications.

    Parses arguments, fetches contests, compares with database, and sends notifications.
    """
    sportz = Sport.__subclasses__()
    choices = dict({sport.name: sport for sport in sportz})

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
    # create_connection("contests.db")
    conn = sqlite3.connect("contests.db")

    for sport_name in args.sport:
        # find matching Sport subclass
        if sport_name not in choices:
            # fail if we don't find one
            raise Exception("Could not find matching Sport subclass")

        sport_obj = choices[sport_name]
        primary_sport = sport_obj.get_primary_sport()

        # if sport == "NFLShowdown":
        #     primary_sport = "NFL"
        # else:
        #     primary_sport = sport

        # get contests from url
        url = f"https://www.draftkings.com/lobby/getcontests?sport={primary_sport}"

        response_contests, draft_groups = get_dk_lobby(sport_obj, url)

        # create list of Contest objects
        contests = [Contest(c, sport_obj.name) for c in response_contests]
        # get double ups from list of Contests

        double_ups = get_double_ups(
            contests,
            draft_groups,
            min_entry_fee=sport_obj.dub_min_entry_fee,
            entries=sport_obj.dub_min_entries,
        )

        # create table if it doesn't exist
        db_create_table(conn)

        # compare new double ups to DB
        new_contests = db_compare_contests(conn, double_ups)

        if new_contests:
            # find contests matching the new contest IDs
            matching_contests = [c for c in contests if c.id in new_contests]

            discord_message = ""
            for contest in matching_contests:
                message = "New dub found! [{:%Y-%m-%d}] Name: {} ID: {} Entry Fee: {} Entries: {}".format(
                    contest.start_dt,
                    contest.name,
                    contest.id,
                    contest.entry_fee,
                    contest.entries,
                )
                logger.info(message)

                discord_message += message + "\n"

            # insert new double ups into DB
            db_insert_contests(conn, matching_contests)
            send_discord_notification(bot, sport_obj.name, discord_message)
            # last_row_id = insert_contests(conn, matching_contests)
            # print("last_row_id: {}".format(last_row_id))


if __name__ == "__main__":
    main()
