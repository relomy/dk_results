"""Find new double ups and print out a message when a new one is found."""

import argparse
import datetime
import sqlite3
from bs4 import BeautifulSoup

import browsercookie
import requests

from classes.contest import Contest

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


def get_dk_lobby(url):
    """Get contests from the DraftKings lobby. Returns a list."""
    # set cookies based on Chrome session
    # print(url)

    response = requests.get(url, headers=HEADERS, cookies=COOKIES).json()

    contests = get_contests_from_response(response)
    draft_groups = get_draft_groups_from_response(response)

    return contests, draft_groups


def get_contests_from_response(response):
    """Get contests from the DraftKings lobby. Returns a list."""
    if isinstance(response, list):
        response_contests = response
    elif "Contests" in response:
        response_contests = response["Contests"]
    else:
        print("response isn't a dict or a list??? exiting")
        exit()

    return response_contests


def get_draft_groups_from_response(response):
    """Get draft groups from lobby/json."""

    response_draft_groups = []
    for draft_group in response["DraftGroups"]:
        # dg['StartDateEst'] should be mostly the same for draft groups, (might
        # not be the same for the rare long-running contest) and should be the
        # date we're looking for (game date in US time).
        # date = get_salary_date(response["DraftGroups"])
        # date = get_salary_date(draft_group)
        # contest_type_id = draft_group["ContestTypeId"]
        tag = draft_group["DraftGroupTag"]
        suffix = draft_group["ContestStartTimeSuffix"].strip()
        draft_group_id = draft_group["DraftGroupId"]

        # only care about featured draftgroups and those with no suffix
        if tag != "Featured" or suffix is not "(PGA TOUR)" or suffix is not None:
            print(
                "Skipping : tag {0} draft_group_id {1} [suffix: {2}]".format(
                    tag, draft_group_id, suffix
                )
            )
            continue

        print(
            "Appending : tag {0} draft_group_id {1} [suffix: {2}]".format(
                tag, draft_group_id, suffix
            )
        )

        # print(
        #     "Adding draft_group for [{0}]: draft group {1} contest type {2} [suffix: {3}]".format(
        #         date, draft_group_id, contest_type_id, suffix
        #     )
        # )
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


def get_double_ups(
    contests, draft_groups, min_entry_fee=1, max_entry_fee=50, entries=200
):
    """Find $1-$10 contests with atleast n entries"""
    contest_list = []
    for contest in contests:
        # skip contests not for today
        # if contest.start_dt.date() != datetime.datetime.today().date():
        #     continue

        # keep track of single-entry double-ups
        if (
            contest.entries >= entries
            and contest.entry_fee >= min_entry_fee
            and contest.entry_fee <= max_entry_fee
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
    """Check contest ids with dk_id in database"""

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
        print("sqlite error: ", err.args[0])


def db_insert_contests(conn, contests):
    """Insert given contests in database"""
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
            print("sqlite error: ", err.args[0])

    # commit database
    conn.commit()

    return cur.lastrowid


def db_update_contest_data_for_contests(conn, contests_to_update):
    """Update contest fields based on get_contest_data()."""
    cur = conn.cursor()

    sql = (
        "UPDATE contests "
        "SET positions_paid=?, status=?, completed=? "
        "WHERE dk_id=?"
    )

    try:
        cur.executemany(sql, contests_to_update)
        conn.commit()
        print(f"Total {cur.rowcount} records updated successfully!")
    except sqlite3.Error as err:
        print("sqlite error: ", err.args[0])


# def db_check_contests_for_update(conn, contests_to_update):
#     """Check if contests need to be updated."""
#     cur = conn.cursor()

#     # store count of current list
#     contests_count = len(contests_to_update)

#     try:
#         # execute SQL command
#         dk_ids = [c[3] for c in contests_to_update]
#         # find all contests which supposedly need to be updated
#         sql = (
#             "SELECT positions_paid, status, completed, dk_id "
#             "FROM contests "
#             "WHERE dk_id IN ({0})"
#         ).format(", ".join("?" for _ in dk_ids))
#         cur.execute(sql, dk_ids)

#         # fetch rows
#         rows = cur.fetchall()

#         for row in rows:
#             # loop through each contest and see if anything is different
#             for contest in contests_to_update:
#                 if list(row) == contest:
#                     # # if we find the right contest
#                     # if row[3] == contest[3]:
#                     #     # and everything matches
#                     #     if (
#                     #         row[0] == contest[0]
#                     #         and row[1] == contest[1]
#                     #         and row[2] == contest[2]
#                     #     ):
#                     # remove it from needing an update
#                     contests_to_update.remove(contest)
#                     break

#         print(
#             "There were {} contests to update, but now there are {}".format(
#                 contests_count, len(contests_to_update)
#             )
#         )
#         # if there are any contests left to update, update them
#         if contests_to_update:
#             db_update_contest_data_for_contests(conn, contests_to_update)

#     except sqlite3.Error as err:
#         print("sqlite error in check_db_contests_for_update(): ", err.args[0])


def check_db_contests_for_completion(conn):
    """Check each contest for completion/positions_paid data."""
    # get cursor
    cur = conn.cursor()

    try:
        # execute SQL command
        sql = (
            "SELECT dk_id, draft_group, positions_paid, status, completed "
            "FROM contests "
            "WHERE start_date <= datetime('now', 'localtime') "
            "  AND (positions_paid IS NULL OR completed = 0)"
        )
        cur.execute(sql)

        # fetch rows
        rows = cur.fetchall()

        contests_to_update = []
        for row in rows:
            contest_data = get_contest_data(row[0])

            if contest_data:
                # if contest data is different, append list
                if (
                    row[2] != contest_data["positions_paid"]
                    or row[3] != contest_data["status"]
                    or row[4] != contest_data["completed"]
                ):
                    contests_to_update.append(
                        (
                            contest_data["positions_paid"],
                            contest_data["status"],
                            contest_data["completed"],
                            row[0],
                        )
                    )

        if contests_to_update:
            # db_check_contests_for_update(conn, contests_to_update)
            db_update_contest_data_for_contests(conn, contests_to_update)

    except sqlite3.Error as err:
        print("sqlite error [check_db_contests_for_completion()]: ", err.args[0])


def get_contest_data(contest_id):
    """Pull contest data (positions paid, status, etc.) with BeautifulSoup"""
    url = f"https://www.draftkings.com/contest/gamecenter/{contest_id}"

    response = requests.get(url, headers=HEADERS, cookies=COOKIES)
    soup = BeautifulSoup(response.text, "html.parser")

    try:
        header = soup.find_all(class_="top")[0].find_all("h4")
        info_header = (
            soup.find_all(class_="top")[0]
            .find_all(class_="info-header")[0]
            .find_all("span")
        )
        status = info_header[3].string.strip().upper()
        # print("Positions paid: %s".format(int(info_header[4].string)))
        if status in ["COMPLETED", "LIVE"]:
            # print(f"contest {contest_id} is {status}")
            # print(
            #     "name: {} total_prizes: {} date: {} entries: {} positions_paid: {}".format(
            #         header[0].string,
            #         header[1].string,
            #         info_header[0].string,
            #         info_header[2].string,
            #         info_header[4].string,
            #     )
            # )

            # set completed status
            completed = 1 if status == "COMPLETED" else 0

            return {
                "completed": completed,
                "status": status,
                "name": header[0].string,
                "total_prizes": header[1].string,
                "date": info_header[0].string,
                "entries": int(info_header[2].string),
                "positions_paid": int(info_header[4].string),
            }
            # DKContest.objects.update_or_create(
            #     dk_id=contest_id,
            #     defaults={
            #         "name": header[0].string,
            #         "total_prizes": dollars_to_decimal(header[1].string),
            #         "date": datestr_to_date(info_header[0].string),
            #         "entries": int(info_header[2].string),
            #         "positions_paid": int(info_header[4].string),
            #     },
            # )

        return None
        # print("Contest {} is still in progress".format(contest_id))
    except IndexError:
        # This error occurs for old contests whose pages no longer are
        # being served.
        # IndexError: list index out of range
        pass
        # print("Couldn't find DK contest with id {}".format(contest_id))


# def get_contest_prize_data(contest_id):
#     url = "https://www.draftkings.com/contest/detailspop"
#     params = {
#         "contestId": contest_id,
#         "showDraftButton": False,
#         "defaultToDetails": True,
#         "layoutType": "legacy",
#     }
#     response = requests.get(url, headers=HEADERS, cookies=COOKIES, params=params)
#     soup = BeautifulSoup(response.text, "html.parser")

#     try:
#         payouts = soup.find_all(id="payouts-table")[0].find_all("tr")
#         entry_fee = soup.find_all("h2")[0].text.split("|")[2].strip()
#         for payout in payouts:
#             places, payout = [x.string for x in payout.find_all("td")]
#             places = [place_to_number(x.strip()) for x in places.split("-")]
#             top, bottom = (places[0], places[0]) if len(places) == 1 else places
#     except IndexError as ex:
#         # See comment in get_contest_data()
#         print("Couldn't find DK contest with id %s: %s", contest_id, ex)


def temp_add_column(conn):
    """TODO: REMOVE"""
    cur = conn.cursor()

    try:
        sql = "ALTER TABLE contests ADD COLUMN completed INTEGER DEFAULT 0"
        cur.execute(sql)
    except sqlite3.Error:  # as err:
        pass
        # print("sqlite error: ", err.args[0])

    try:
        sql = "ALTER TABLE contests ADD COLUMN status TEXT"
        cur.execute(sql)
    except sqlite3.Error:  # as err:
        pass
        # print("sqlite error: ", err.args[0])


def main():
    """Find new double ups."""
    # parse arguments
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-s",
        "--sport",
        choices=["NBA", "NFL", "CFB", "GOLF", "NHL", "MLB", "TEN"],
        required=True,
        help="Type of contest (NBA, NFL, GOLF, CFB, NHL, MLB, or TEN)",
        nargs="+",
    )
    parser.add_argument("-v", "--verbose", help="Increase verbosity")
    args = parser.parse_args()

    # create connection to database file
    # create_connection("contests.db")
    conn = sqlite3.connect("contests.db")

    # temp_add_column
    temp_add_column(conn)

    # update old contests
    check_db_contests_for_completion(conn)

    for sport in args.sport:
        # get contests from url
        url = f"https://www.draftkings.com/lobby/getcontests?sport={sport}"

        response_contests, draft_groups = get_dk_lobby(url)

        # create list of Contest objects
        contests = [Contest(c, sport) for c in response_contests]

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

        # get double ups from list of Contests
        double_ups = get_double_ups(contests, draft_groups)

        # create table if it doesn't exist
        db_create_table(conn)

        # compare new double ups to DB
        new_contests = db_compare_contests(conn, double_ups)

        if new_contests:
            # find contests matching the new contest IDs
            matching_contests = [c for c in contests if c.id in new_contests]

            for contest in matching_contests:
                print(
                    "New dub found! [{:%Y-%m-%d}] Name: {} ID: {} Entry Fee: {} Entries: {}".format(
                        contest.start_dt,
                        contest.name,
                        contest.id,
                        contest.entry_fee,
                        contest.entries,
                    )
                )
                # print(contest)

            # insert new double ups into DB
            db_insert_contests(conn, matching_contests)
            # last_row_id = insert_contests(conn, matching_contests)
            # print("last_row_id: {}".format(last_row_id))


if __name__ == "__main__":
    main()
