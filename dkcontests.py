"""
Find contests for a sport and print cron job.

URL: https://www.draftkings.com/lobby/getcontests?sport=NBA
Response format: {
    'SelectedSport': 4,
    # To find the correct contests, see: find_new_contests()
    'Contests': [{
        'id': '16911618',                              # Contest id
        'n': 'NBA $375K Tipoff Special [$50K to 1st]', # Contest name
        'po': 375000,                                  # Total payout
        'm': 143750,                                   # Max entries
        'a': 3.0,                                      # Entry fee
        'sd': '/Date(1449619200000)/'                  # Start date
        'dg': 8014                                     # Draft group
        ... (the rest is unimportant)
    },
    ...
    ],
    # Draft groups are for querying salaries, see: run()
    'DraftGroups': [{
        'DraftGroupId': 8014,
        'ContestTypeId': 5,
        'StartDate': '2015-12-09T00:00:00.0000000Z',
        'StartDateEst': '2015-12-08T19:00:00.0000000',
        'Sport': 'NBA',
        'GameCount': 6,
        'ContestStartTimeSuffix': null,
        'ContestStartTimeType': 0,
        'Games': null
    },
    ...
    ],
    ... (the rest is unimportant)
}
"""

import argparse
import datetime
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

    def get_dt_from_timestamp(self, timestamp_str):
        timestamp = float(re.findall(r"[^\d]*(\d+)[^\d]*", timestamp_str)[0])
        return datetime.datetime.fromtimestamp(timestamp / 1000)

    def __str__(self):
        return f"{vars(self)}"


def get_contests(url):
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


def get_contest(contests, dt, entry_fee=25, query=None, exclude=None, largest=True):
    """Return largest contest from a list of Contests.

    Parameters
    ----------
    contests : list of Contests
        list of DraftKings contests
    dt : datetime.datetime
        the datetime to filter
    entry_fee : int, optional
        contest entry fee, by default 25
    query : string, optional
        include string in contest name, by default None
    exclude : string, optional
        exclude string in contest name, by default None

    Returns
    -------
    Contest
        returns largest (entries) contest or None

    """
    print("contests size: {}".format(len(contests)))
    contest_list = []

    # add contest to list if it matches criteria
    contest_list = [
        c for c in contests if match_contest_criteria(c, dt, entry_fee, query, exclude)
    ]

    print("number of contests meeting requirements: {}".format(len(contest_list)))

    # sorted_list = sorted(contest_list, key=lambda x: x.entries, reverse=True)
    if contest_list:
        if largest:
            return max(contest_list, key=lambda x: x.entries)
        else:
            return contest_list

    return None


def match_contest_criteria(
    contest, dt, entry_fee=25, min_entries=229, query=None, exclude=None
):
    """Use arguments to filter contest criteria.

    Parameters
    ----------
    contest : Contest
        DraftKings contest
    dt : [datetime.datetime]
        the datetime on which we wish to filter
    entry_fee : int, optional
        the entry fee for the contest (default: {25}), by default 25
    query : string, optional
        include string in contest name, by default None
    exclude : string, optional
        exclude string in contest name, by default None

    Returns
    -------
    boolean
        returns true if all criteria matched, otherwise false

    """
    if (
        contest.start_dt.date() == dt.date()
        and contest.max_entry_count == 1
        and contest.entry_fee == entry_fee
        and contest.is_double_up
        and contest.is_guaranteed
    ):
        # if contest entries does not meet minimum entry count, return false
        if contest.entries < min_entries:
            return False

        # if exclude is in the name, return false
        if exclude and exclude in contest.name:
            return False

        # if query is not in the name, return false
        if query and query not in contest.name:
            return False

        return True

    return False


def get_contests_by_entries(contests, entry_fee, limit):
    return sorted(
        [c for c in contests if c.entry_fee == entry_fee and c.entries > limit],
        key=lambda x: x.entries,
        reverse=True,
    )


def set_cron_interval(contest, sport_length):
    # add about how long the slate should be
    end_dt = contest.start_dt + datetime.timedelta(hours=sport_length)

    # if dates are the same, we don't add days or hours
    if contest.start_dt.date() == end_dt.date():
        # print("dates are the same")
        hours = f"{contest.start_dt:%H}-{end_dt:%H}"
        days = f"{contest.start_dt:%d}"
    else:
        # print("dates are not the same - that means end_dt extends into the next day")
        # don't double print 00s
        if end_dt.strftime("%H") == "00":
            hours = f"{end_dt:%H},{contest.start_dt:%H}-23"
        else:
            hours = f"00-{end_dt:%H},{contest.start_dt:%H}-23"
        days = f"{contest.start_dt:%d}-{end_dt:%d}"

    return f"{hours} {days} {end_dt:%m} *"


def print_cron_job(contest, sport):
    print(contest)
    home_dir = "/home/pi/Desktop"
    pipenv_path = "/usr/local/bin/pipenv"

    # set interval and length depending on sport
    if sport == "NBA":
        sport_length = 6
        dl_interval = "*/10"
        get_interval = "*/5"
    elif sport == "NFL":
        sport_length = 6
        dl_interval = "*/10"
        get_interval = "*/5"
    elif sport == "CFB":
        sport_length = 6
        dl_interval = "*/10"
        get_interval = "*/5"
    elif sport == "MLB":
        sport_length = 7
        dl_interval = "1-59/15"
        get_interval = "2-59/10"
    elif sport == "PGA":
        sport_length = 8
        dl_interval = "3-59/30"
        get_interval = "4-59/15"
    elif sport == "TEN":
        sport_length = 15
        dl_interval = "4-59/15"
        get_interval = "5-59/10"

    # set some long strings up as variables
    py_str = f"cd {home_dir}/dk_results && {pipenv_path} run python"
    dl_str = f"{py_str} download_DK_salary.py"
    get_str = f"export DISPLAY=:1 && {py_str} main.py"
    cron_str = set_cron_interval(contest, sport_length)
    out_str = f"{home_dir}/{sport}_results.log 2>&1"
    file_str = f"DKSalaries_{sport}_{contest.start_dt:%A}.csv"

    # print(
    #     f"{dl_interval} {cron_str} {dl_str} -s {sport} -dg {contest.draft_group} >> {out_str}"
    # )
    print(
        f"Download CSV for this slate:\n{dl_str} -s {sport} -dg {contest.draft_group} -f {file_str}\n"
    )
    print(
        f"{get_interval} {cron_str} {get_str} -s {sport} -i {contest.id} -dg {contest.draft_group} >> {out_str}"
    )


def valid_date(date_string):
    """Check date argument to determine if it is a valid.

    Arguments
    ---------
        date_string {string} -- date from argument

    Raises
    ------
        argparse.ArgumentTypeError:

    Returns
    -------
        {datetime.datetime} -- YYYY-MM-DD format

    """
    try:
        return datetime.datetime.strptime(date_string, "%Y-%m-%d")
    except ValueError:
        msg = "Not a valid date: '{0}'.".format(date_string)
        raise argparse.ArgumentTypeError(msg)


def get_stats(contests):
    stats = {}
    for c in contests:
        start_date = c.start_dt.strftime("%Y-%m-%d")

        # initialize stats[start_date] if it doesn't exist
        if start_date not in stats:
            stats[start_date] = {"count": 0}

        stats[start_date]["count"] += 1

        # keep track of single-entry double-ups
        if c.max_entry_count == 1 and c.is_guaranteed and c.is_double_up:
            # initialize stats[start_date]["dubs"] if it doesn't exist
            if "dubs" not in stats[start_date]:
                stats[start_date]["dubs"] = {c.entry_fee: 0}

            # initialize stats[start_date]["dubs"][c.entry_fee] if it doesn't exist
            if c.entry_fee not in stats[start_date]["dubs"]:
                stats[start_date]["dubs"][c.entry_fee] = 0

            stats[start_date]["dubs"][c.entry_fee] += 1

    return stats


def print_stats(contests):
    stats = get_stats(contests)

    if stats:
        print("Breakdown per date:")
        for date, values in sorted(stats.items()):
            print(f"{date} - {values['count']} total contests")

            if "dubs" in values:
                print("Single-entry double ups:")
                for entry_fee, count in sorted(values["dubs"].items()):
                    print(f"     ${entry_fee}: {count} contest(s)")


def create_connection(db_file):
    """ create a database connection to a SQLite database """
    conn = None
    try:
        conn = sqlite3.connect(db_file)
        print(sqlite3.sqlite_version)
    except sqlite3.Error as e:
        print(e)
    finally:
        if conn:
            conn.close()


def upsert_contest():
    pass


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

    # create list of Contest objects
    contests = [Contest(c) for c in response_contests]

    # print stats for contests
    print_stats(contests)

    # create_connection("contests.db")
    # conn = sqlite3.connect("contests.db")
    # c = conn.cursor()

    c.execute(
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

    # insert new contests
    contests = get_contest(contests, args.date, largest=False)

    # parse contest and return single contest which matches argument criteria
    contest = get_contest(contests, args.date, args.entry, args.query, args.exclude)

    # check if contest is empty
    if not contest:
        exit("No contests found.")

    # change GOLF back to PGA
    if args.sport == "GOLF":
        args.sport = "PGA"

    # print out cron job for our other scripts
    print_cron_job(contest, args.sport)


if __name__ == "__main__":
    main()
