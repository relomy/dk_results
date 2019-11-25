"""Find new double ups and print out a message when a new one is found."""

import argparse
import datetime
import json
import re
import sqlite3

import browsercookie
import requests

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


class Contest:
    """Object representing a DraftKings contest from json."""

    def __init__(self, contest):
        self.start_date = contest["sd"]
        self.name = contest["n"]
        self.id = contest["id"]
        self.draft_group = contest["dg"]
        self.total_prizes = contest["po"]
        self.entries = contest["m"]
        self.entry_fee = contest["a"]
        self.entry_count = contest["ec"]
        self.max_entry_count = contest["mec"]
        self.attr = contest["attr"]
        self.is_guaranteed = False
        self.is_double_up = False

        self.start_dt = self.get_dt_from_timestamp(self.start_date)

        if "IsDoubleUp" in self.attr:
            self.is_double_up = self.attr["IsDoubleUp"]

        if "IsGuaranteed" in self.attr:
            self.is_guaranteed = self.attr["IsGuaranteed"]

    @staticmethod
    def get_dt_from_timestamp(timestamp_str):
        """Convert timestamp to datetime object."""
        timestamp = float(re.findall(r"[^\d]*(\d+)[^\d]*", timestamp_str)[0])
        return datetime.datetime.fromtimestamp(timestamp / 1000)

    def __str__(self):
        return f"{vars(self)}"


def get_contests(url):
    """Get contests from the DraftKings lobby. Returns a list."""
    # set cookies based on Chrome session
    print(url)

    response = requests.get(url, headers=HEADERS, cookies=COOKIES).json()
    response_contests = {}
    if isinstance(response, list):
        print("response is a list")
        response_contests = response
    elif "Contests" in response:
        print("response is a dict")
        response_contests = response["Contests"]
    else:
        print("response isn't a dict or a list??? exiting")
        exit()

    return response_contests


def get_draft_groups(url):
    """Get draft groups from lobby/json."""

    # set cookies based on Chrome session
    print(url)

    response = requests.get(url, headers=HEADERS, cookies=COOKIES).json()

    response_draft_groups = []
    for draft_group in response["DraftGroups"]:
        # dg['StartDateEst'] should be mostly the same for draft groups, (might
        # not be the same for the rare long-running contest) and should be the
        # date we're looking for (game date in US time).
        # date = get_salary_date(response["DraftGroups"])
        date = get_salary_date(draft_group)
        tag = draft_group["DraftGroupTag"]
        suffix = draft_group["ContestStartTimeSuffix"]
        draft_group_id = draft_group["DraftGroupId"]
        contest_type_id = draft_group["ContestTypeId"]

        # only care about featured draftgroups and those with no suffix
        if tag != "Featured" or suffix is not None:
            print(
                "Skipping [{0}]: draft group {1} contest type {2} [suffix: {3}]".format(
                    date, draft_group_id, contest_type_id, suffix
                )
            )
            continue

        print(
            "Adding draft_group for [{0}]: draft group {1} contest type {2} [suffix: {3}]".format(
                date, draft_group_id, contest_type_id, suffix
            )
        )
        response_draft_groups.append(draft_group_id)
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


def print_stats(contests):
    """Print stats for list of Contest objects."""
    stats = get_stats(contests)

    if stats:
        print("Breakdown per date:")
        for date, values in sorted(stats.items()):
            print(f"{date} - {values['count']} total contests")

            if "dubs" in values:
                print("Single-entry double ups:")
                for entry_fee, count in sorted(values["dubs"].items()):
                    print(f"     ${entry_fee}: {count} contest(s)")


def get_double_ups(contests, draft_groups, entries=100):
    """Find $1-$10 contests with atleast n entries"""
    contest_list = []
    for contest in contests:
        # skip contests not for today
        if contest.start_dt.date() != datetime.datetime.today().date():
            continue

        # keep track of single-entry double-ups
        if (
            contest.entries >= entries
            and contest.entry_fee >= 1
            and contest.entry_fee <= 10
            and contest.max_entry_count == 1
            and contest.is_guaranteed
            and contest.is_double_up
            and contest.draft_group in draft_groups
        ):
            contest_list.append(contest)

    return contest_list


def get_salary_date(draft_group):
    """Return the salary date in format YYYY-MM-DD"""
    return datetime.datetime.strptime(
        draft_group["StartDateEst"].split("T")[0], "%Y-%m-%d"
    ).date()


def create_connection(db_file):
    """Create a database connection to a SQLite database."""
    conn = None
    try:
        conn = sqlite3.connect(db_file)
        print(sqlite3.sqlite_version)
    except sqlite3.Error as err:
        print(err)
    finally:
        if conn:
            conn.close()


def create_table(conn):
    """Create table if it does not exist."""
    cur = conn.cursor()

    cur.execute(
        """ CREATE TABLE IF NOT EXISTS contests (
        dk_id INTEGER PRIMARY KEY,
        name varchar(50) NOT NULL,
        start_date datetime NOT NULL,
        draft_group INTEGER NOT NULL,
        total_prizes INTEGER NOT NULL,
        entries INTEGER NOT NULL,
        positions_paid INTEGER,
        entry_fee INTEGER NOT NULL,
        entry_count INTEGER NOT NULL,
        max_entry_count INTEGER
    )"""
    )


def compare_contests_with_db(conn, contests):
    """Check contest ids with dk_id in database"""

    # get cursor
    cur = conn.cursor()

    # get all rows with matching dk_ids
    ids = [c.id for c in contests]

    try:
        # execute SQL command
        sql = "SELECT dk_id FROM contests WHERE dk_id IN ({0})".format(
            ", ".join("?" for _ in ids)
        )
        cur.execute(sql, ids)

        # fetch rows
        rows = cur.fetchall()

        # return None if nothing found
        if not rows:
            print("All contest IDs are accounted for in database")
            return None

        # if there are rows, remove found id from ids list
        if rows and len(rows) >= 1:
            for row in rows:
                if row[0] in ids:
                    ids.remove(row[0])

        return ids

    except sqlite3.Error as err:
        print("sqlite error: ", err.args[0])


def insert_contests(conn, contests):
    """Insert given contests in database"""
    # create SQL command
    sql = (
        "INSERT INTO contests(dk_id, name, start_date, draft_group, total_prizes,"
        + "entries, entry_fee, entry_count, max_entry_count)"
        + "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)"
    )

    cur = conn.cursor()

    # create tuple for SQL command
    for contest in contests:
        tpl_contest = (
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
            print("sqlite error: ", err.args[0])

    # commit database
    conn.commit()

    return cur.lastrowid


def main():
    """"""
    # parse arguments
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-s",
        "--sport",
        choices=["NBA", "NFL", "CFB", "GOLF", "NHL", "MLB", "TEN"],
        required=True,
        help="Type of contest (NBA, NFL, GOLF, CFB, NHL, MLB, or TEN)",
    )
    parser.add_argument(
        "-l", "--live", action="store_true", default="", help="Get live contests"
    )
    parser.add_argument(
        "-e", "--entry", type=int, default=25, help="Entry fee (25 for $25)"
    )
    parser.add_argument("-q", "--query", help="Search contest name")
    parser.add_argument("-x", "--exclude", help="Exclude from search")
    parser.add_argument(
        "-d",
        "--date",
        help="The Start Date - format YYYY-MM-DD",
        default=datetime.datetime.today(),
        type=valid_date,
    )
    args = parser.parse_args()
    print(args)

    live = ""
    if args.live:
        live = "live"

    create_connection("contests.db")

    # get contests from url
    url = f"https://www.draftkings.com/lobby/get{live}contests?sport={args.sport}"
    response_contests = get_contests(url)

    draft_groups = get_draft_groups(url)

    # create list of Contest objects
    contests = [Contest(c) for c in response_contests]

    # temp
    # contests = []
    # with open("getcontests.json", "r") as fp:
    #     response = json.loads(fp.read())
    #     response_contests = {}
    #     if isinstance(response, list):
    #         print("response is a list")
    #         response_contests = response
    #     elif "Contests" in response:
    #         print("response is a dict")
    #     response_contests = response["Contests"]
    #     contests = [Contest(c) for c in response_contests]

    # print stats for contests
    print_stats(contests)

    # get double ups from list of Contests
    double_ups = get_double_ups(contests, draft_groups)

    # create connection to database file
    # create_connection("contests.db")
    conn = sqlite3.connect("contests.db")

    # create table if it doesn't exist
    create_table(conn)

    # test stuff
    test = 81358543
    curr = conn.cursor()
    curr.execute("SELECT dk_id FROM contests WHERE dk_id = ?", (test,))
    data = curr.fetchone()
    if data and len(data) >= 1:
        print("Contest {} found with rowids {}".format(test, data[0]))
    else:
        print("There is no contest with dk_id {}".format(test))

    # get new double ups
    # contests = get_contest(contests, args.date, largest=False)

    # compare new double ups to DB
    new_contests = compare_contests_with_db(conn, double_ups)

    if new_contests:
        # find contests matching the new contest IDs
        matching_contests = [c for c in contests if c.id in new_contests]

        for contest in matching_contests:
            print(
                "New double up found! Name: {0} ID: {1} Entry Fee: {2} Entries: {3}".format(
                    contest.name, contest.id, contest.entry_fee, contest.entries
                )
            )
            print(contest)

        # insert new double ups into DB
        last_row_id = insert_contests(conn, matching_contests)
        print("last_row_id: {}".format(last_row_id))


if __name__ == "__main__":
    main()
