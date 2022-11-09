"""Find new double ups and print out a message when a new one is found."""


import argparse
import datetime
import logging
import logging.config
import sqlite3
import sys

from os import environ

import browsercookie
import requests

from classes.sport import CFBSport, GolfSport, NBASport, NFLSport, Sport
from classes.contest import Contest
from bot.discord import Discord

# load the logging configuration
logging.config.fileConfig("logging.ini")

logger = logging.getLogger(__name__)

COOKIES = browsercookie.chrome()
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


def get_dk_lobby(sport, url):
    """Get contests from the DraftKings lobby. Returns a list."""
    # set cookies based on Chrome session
    # logger.debug(url)

    response = requests.get(url, headers=HEADERS, cookies=COOKIES).json()

    contests = get_contests_from_response(response)
    draft_groups = get_draft_groups_from_response(response, sport)

    return contests, draft_groups


def get_contests_from_response(response):
    """Get contests from the DraftKings lobby. Returns a list."""
    if isinstance(response, list):
        response_contests = response
    elif "Contests" in response:
        response_contests = response["Contests"]
    else:
        logger.error("response isn't a dict or a list??? exiting")
        sys.exit()

    return response_contests


def get_draft_groups_from_response(response, sport_obj: Sport):
    """Get draft groups from lobby/json."""
    response_draft_groups = []
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

        if suffix is not None:
            suffix = suffix.strip()

        suffix_list = [
            "(PGA)",
            "(PGA TOUR)",
            "(Weekend PGA TOUR)",
            "(Round 1 PGA TOUR)",
            "(Round 2 PGA TOUR)",
            "(Round 3 PGA TOUR)",
            "(Round 4 PGA TOUR)",
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
            if sport_obj.suffixes:
                if suffix is not None and suffix.strip() in sport_obj.suffixes:
                    # python won't convert the DK state time because of the milliseconds
                    dt_start_date = datetime.datetime.fromisoformat(start_date_est[:-8])

                    logger.debug(
                        "[%4s] Found PRIMETIME!!!: start time: [%s] start date: [%s] dg: [%d] tag [%s] suffix: [%s]",
                        sport,
                        dt_start_date.time(),
                        dt_start_date,
                        # start_date_est,
                        draft_group_id,
                        tag,
                        suffix,
                    )
                continue

            if suffix is None or suffix.strip() in suffix_list:
                logger.info(
                    "[%4s] Append: start date: [%s] dg: [%d] tag [%s] suffix: [%s]",
                    sport,
                    start_date_est,
                    draft_group_id,
                    tag,
                    suffix,
                )
                response_draft_groups.append(draft_group_id)
                continue

            # elif "vs" in suffix:
            #     # python won't convert the DK state time because of the milliseconds
            #     dt_start_date = datetime.datetime.fromisoformat(start_date_est[:-8])

            #     if is_time_between(
            #         datetime.time(20, 00), datetime.time(23, 59), dt_start_date.time()
            #     ):
            #         logger.debug(
            #             "[%4s] Found VS!!!!!!!!!!!!!!: start time: [%s] start date: [%s] dg: [%d] tag [%s] suffix: [%s]",
            #             sport,
            #             dt_start_date.time(),
            #             dt_start_date,
            #             # start_date_est,
            #             draft_group_id,
            #             tag,
            #             suffix,
            #         )
            #     continue

        logger.debug(
            "[%4s]   Skip: start date: [%s] dg: [%d] tag [%s] suffix: [%s]",
            sport,
            start_date_est,
            draft_group_id,
            tag,
            suffix,
        )

        # print(
        #     "Adding draft_group for [{0}]: draft group {1} contest type {2} [suffix: {3}]".format(
        #         date, draft_group_id, contest_type_id, suffix
        #     )
        # )

        # row = get_salary_csv(sport, draft_group_id, contest_type_id, date)
        # if date not in rows_by_date:
        #     rows_by_date[date] = []
        # rows_by_date[date] += row

    return response_draft_groups


def valid_date(date_string):
    """Check date argument to determine if it is a valid."""
    try:
        return datetime.datetime.strptime(date_string, "%Y-%m-%d")
    except ValueError:
        msg = "Not a valid date: '{0}'.".format(date_string)
        raise argparse.ArgumentTypeError(msg)


def get_stats(contests):
    """Get stats for list of Contest objects."""
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
    contests, draft_groups, min_entry_fee=5, max_entry_fee=50, entries=125,
) -> list:
    """Find contests matching criteria."""

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


def contest_meets_criteria(contest, criteria):
    """Ensure contests meet criteria."""
    return (
        contest.entries >= criteria["entries"]
        and contest.draft_group in criteria["draft_groups"]
        and contest.entry_fee >= criteria["min_entry_fee"]
        and contest.entry_fee <= criteria["max_entry_fee"]
        and contest.max_entry_count == 1
        and contest.is_guaranteed
        and contest.is_double_up
    )


def get_salary_date(draft_group):
    """Return the salary date in format YYYY-MM-DD."""
    return datetime.datetime.strptime(
        draft_group["StartDateEst"].split("T")[0], "%Y-%m-%d"
    ).date()


def create_connection(db_file):
    """Create a database connection to a SQLite database."""
    conn = None
    try:
        conn = sqlite3.connect(db_file)
        logger.debug(sqlite3.sqlite_version)
    except sqlite3.Error as err:
        logger.error(err)
    finally:
        if conn:
            conn.close()


def db_create_table(conn):
    """Create table if it does not exist."""
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


def db_compare_contests(conn, contests):
    """Check contest ids with dk_id in database."""
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


def db_insert_contests(conn, contests):
    """Insert given contests in database."""
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


def is_time_between(begin_time, end_time, check_time=None):
    # If check time is not given, default to current UTC time
    check_time = check_time or datetime.datetime.utcnow().time()
    if begin_time < end_time:
        # return check_time >= begin_time and check_time <= end_time
        return begin_time <= check_time <= end_time

    # crosses midnight
    return check_time >= begin_time or check_time <= end_time


def set_quiet_verbosity() -> None:
    logger.setLevel(logging.INFO)


def main():
    """Find new double ups."""
    sportz = Sport.__subclasses__()
    choices = dict({sport.name: sport for sport in sportz})

    webhook = environ["DISCORD_WEBHOOK"]

    bot = Discord(webhook)

    # parse arguments
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
    args = parser.parse_args()

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

                # print(contest)

            if sport_obj.name == "NBA":
                bot.send_message(
                    ":basketball: " + discord_message + " <@&1034206287153594470>"
                )
            elif sport_obj.name == "CFB":
                bot.send_message(
                    ":football: " + discord_message + " <@&1034214536544268439>"
                )
            elif sport_obj.name == "GOLF":
                bot.send_message(
                    ":golf: " + discord_message + " <@&1040014001452630046>"
                )

            # insert new double ups into DB
            db_insert_contests(conn, matching_contests)
            # last_row_id = insert_contests(conn, matching_contests)
            # print("last_row_id: {}".format(last_row_id))


if __name__ == "__main__":
    main()
