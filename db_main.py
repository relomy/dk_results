""""""

import argparse
import csv
import datetime
import io
import logging
import logging.config
import pickle
import sqlite3
import time
import zipfile
from os import getenv

import browsercookie
import requests
import selenium.webdriver.chrome.service as chrome_service
from pytz import timezone
from selenium import webdriver

from classes.dfssheet import DFSSheet
from classes.draftkings import Draftkings
from classes.results import Results

# load the logging configuration
logging.config.fileConfig("logging.ini")

logger = logging.getLogger(__name__)


def pull_contest_zip(contest_id):
    """Pull contest file (so far can be .zip or .csv file)."""

    # try pickle cookies method
    cookies = cj_from_pickle("pickled_cookies_works.txt")
    if cookies:
        result = setup_session(contest_id, cookies)

        logger.debug("type(result): {}".format(type(result)))

        if result is not None:
            logger.debug("pickle method worked!!")
            return result
        else:
            logger.debug("Broken from pickle method")

    # try browsercookie method
    cookies = browsercookie.chrome()

    result = setup_session(contest_id, cookies)
    logger.debug("type(result): {}".format(type(result)))

    if result:
        return result

    # use selenium to refresh cookies
    use_selenium(contest_id)

    # try browsercookie method again
    cookies = browsercookie.chrome()

    result = setup_session(contest_id, cookies)
    logger.debug("type(result): {}".format(type(result)))

    if result is not None:
        logger.debug("SECOND browsercookie method worked!!")
        return result
    else:
        logger.debug("Broken from SECOND browsercookie method")


def use_selenium(contest_id):
    url_contest_csv = (
        f"https://www.draftkings.com/contest/exportfullstandingscsv/{contest_id}"
    )
    bin_chromedriver = getenv("CHROMEDRIVER")
    if not getenv("CHROMEDRIVER"):
        exit("Could not find CHROMEDRIVER in env variable")

    logger.debug(f"Found chromedriver in env variable: {bin_chromedriver}")
    # start headless webdriver
    service = chrome_service.Service(bin_chromedriver)
    service.start()
    logger.debug("Starting driver with options")
    options = webdriver.ChromeOptions()
    options.add_argument("--no-sandbox")
    # options.add_argument("--user-data-dir=/Users/Adam/Library/Application Support/Google/Chrome")
    options.add_argument("--user-data-dir=/home/pi/.config/chromium")
    options.add_argument(r"--profile-directory=Profile 1")
    driver = webdriver.Remote(
        service.service_url, desired_capabilities=options.to_capabilities()
    )

    logger.debug("Performing get on {}".format(url_contest_csv))
    driver.get(url_contest_csv)
    logger.debug(driver.current_url)
    logger.debug("Letting DK load ...")
    time.sleep(5)  # Let DK Load!
    logger.debug(driver.current_url)
    logger.debug("Letting DK load ...")
    time.sleep(5)  # Let DK Load!
    logger.debug(driver.current_url)
    logger.debug("Quitting driver")
    driver.quit()


def setup_session(contest_id, cookies):
    s = requests.Session()
    now = datetime.datetime.now()

    for c in cookies:
        # if the cookies already exists from a legitimate fresh session, clear them out
        if c.name in s.cookies:
            logger.debug("removing {} from 'cookies' -- ".format(c.name), end="")
            cookies.clear(c.domain, c.path, c.name)
        else:
            if not c.expires:
                continue

    logger.debug("adding all missing cookies to session.cookies")
    s.cookies.update(cookies)

    return request_contest_url(s, contest_id)


def request_contest_url(s, contest_id):
    # attempt to GET contest_csv_url
    url_contest_csv = (
        f"https://www.draftkings.com/contest/exportfullstandingscsv/{contest_id}"
    )
    r = s.get(url_contest_csv)
    logger.debug(r.status_code)
    logger.debug(r.url)
    logger.debug(r.headers["Content-Type"])
    # print(r.headers)
    if "text/html" in r.headers["Content-Type"]:
        logger.info("We cannot do anything with html!")
        return None
    # if headers say file is a CSV file
    elif r.headers["Content-Type"] == "text/csv":
        # write working cookies
        with open("pickled_cookies_works.txt", "wb") as f:
            pickle.dump(s.cookies, f)
        # decode bytes into string
        csvfile = r.content.decode("utf-8")
        print(csvfile, file=open(f"contest-standings-{contest_id}.csv", "w"))
        # open reader object on csvfile
        # rdr = csv.reader(csvfile.splitlines(), delimiter=",")
        return list(csv.reader(csvfile.splitlines(), delimiter=","))
    else:
        # write working cookies
        with open("pickled_cookies_works.txt", "wb") as f:
            pickle.dump(s.cookies, f)
        # request will be a zip file
        z = zipfile.ZipFile(io.BytesIO(r.content))
        for name in z.namelist():
            # extract file - it seems easier this way
            path = z.extract(name)
            logger.debug(f"path: {path}")
            with z.open(name) as csvfile:
                logger.debug("name within zipfile: {}".format(name))
                # convert to TextIOWrapper object
                lines = io.TextIOWrapper(csvfile, encoding="utf-8", newline="\r\n")
                # open reader object on csvfile within zip file
                # rdr = csv.reader(lines, delimiter=",")
                return list(csv.reader(lines, delimiter=","))


def cj_from_pickle(filename):
    try:
        with open(filename, "rb") as f:
            return pickle.load(f)
    except FileNotFoundError as e:
        logger.error("File {} not found [{}]".format(filename, e))
        return False


def get_live_contest(conn, sport, entry_fee=25):
    # get cursor
    cur = conn.cursor()

    now = datetime.datetime.now()

    try:
        # execute SQL command
        sql = (
            "SELECT dk_id, draft_group, start_date FROM contests "
            + "WHERE sport=? AND entry_fee=? "
            + "    AND start_date >= date('now')"
            + "ORDER BY start_date"
        )

        cur.execute(sql, (sport, entry_fee))

        # fetch rows
        row = cur.fetchall()

        if row[2]:
            start_date = datetime.datetime.strptime(row[2], "%Y-%m-%d %H:%M:%S")
            if now < start_date:
                logger.debug(
                    "Contest {} has not started yet start_date: {}".format(
                        row[0], start_date
                    )
                )
                return None

        # return
        return row

    except sqlite3.Error as err:
        print("sqlite error: ", err.args[0])


def main():
    """"""
    # parse arguments
    parser = argparse.ArgumentParser()
    choices = [
        "NBA",
        "NFL",
        "CFB",
        "PGAMain",
        "PGAWeekend",
        "PGAShowdown",
        "NHL",
        "MLB",
        "TEN",
    ]
    parser.add_argument(
        "-s",
        "--sport",
        choices=choices,
        required=True,
        help="Type of contest (NBA, NFL, GOLF, CFB, NHL, MLB, or TEN)",
        nargs="+",
    )
    parser.add_argument(
        "--nolineups",
        dest="nolineups",
        action="store_false",
        help="If true, will not print VIP lineups",
    )
    parser.add_argument("-v", "--verbose", help="Increase verbosity")

    args = parser.parse_args()
    print(args)

    # live = ""
    # if args.live:
    #     live = "live"

    # create_connection("contests.db")

    # create connection to database file
    # create_connection("contests.db")
    conn = sqlite3.connect("contests.db")

    now = datetime.datetime.now(timezone("US/Eastern"))

    for sport in args.sport:

        logger.info(sport)

        result = get_live_contest(conn, sport)

        if not result:
            logger.warning(f"There are no live contests for {sport}! Moving on.")
            continue

        # store dk_id and draft_group from database result
        dk_id, draft_group = result

        fn = f"DKSalaries_sport_{now:%A}.csv"

        logger.debug(args)

        dk = Draftkings()

        if draft_group:
            logger.info("Downloading salary file (draft_group: %d)", draft_group)
            dk.download_salary_csv(sport, draft_group, fn)

        # pull contest standings from draftkings
        contest_list = pull_contest_zip(dk_id)

        if contest_list is None:
            raise Exception("pull_contest_zip() - contest_list is None.")
        elif not contest_list:  # contest_list is empty
            raise Exception("pull_contest_zip() - contest_list is empty.")

        sheet = DFSSheet(sport)

        logger.debug(f"Creating Results object Results({sport}, {dk_id}, fn)")
        r = Results(sport, dk_id, fn)
        z = r.players_to_values(sport)
        sheet.write_players(z)
        logger.info("Writing players to sheet")
        sheet.add_last_updated(now)

        if args.nolineups and r.vip_list:
            logger.info("Writing vip_lineups to sheet")
            sheet.write_vip_lineups(r.vip_list)


if __name__ == "__main__":
    main()
