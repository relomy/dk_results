"""Use database and update Google Sheet with contest standings from DraftKings."""

import argparse
import csv
import datetime
import io
import logging
import logging.config
import pickle
import sqlite3
import sys
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

        logger.debug("type(result): %s", type(result))

        if result is not None:
            logger.debug("pickle method worked!!")
            return result

    # try browsercookie method
    logger.debug("First pickle method did not work - trying browsercookie method")
    cookies = browsercookie.chrome()

    result = setup_session(contest_id, cookies)
    logger.debug("type(result): %s", type(result))

    if result:
        return result

    # use selenium to refresh cookies
    use_selenium(contest_id)

    # try browsercookie method again
    cookies = browsercookie.chrome()

    result = setup_session(contest_id, cookies)
    logger.debug("type(result): %s", type(result))

    if result is not None:
        logger.debug("SECOND browsercookie method worked!!")
        return result

    logger.debug("Broken from SECOND browsercookie method")
    return None


def use_selenium(contest_id):
    url_contest_csv = (
        f"https://www.draftkings.com/contest/exportfullstandingscsv/{contest_id}"
    )
    bin_chromedriver = getenv("CHROMEDRIVER")
    if not getenv("CHROMEDRIVER"):
        logger.error("Could not find CHROMEDRIVER in env variable")
        sys.exit()

    logger.debug("Found chromedriver in env variable: %s", {bin_chromedriver})
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

    logger.debug("Performing get on %s", url_contest_csv)
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
    session = requests.Session()

    for cookie in cookies:
        # if the cookies already exists from a legitimate fresh session, clear them out
        if cookie.name in session.cookies:
            logger.debug("removing %s from 'cookies' -- ", cookie.name, end="")
            cookies.clear(cookie.domain, cookie.path, cookie.name)
        else:
            if not cookie.expires:
                continue

    logger.debug("adding all missing cookies to session.cookies")
    session.cookies.update(cookies)

    return request_contest_url(session, contest_id)


def request_contest_url(session, contest_id):
    # attempt to GET contest_csv_url
    url_contest_csv = (
        f"https://www.draftkings.com/contest/exportfullstandingscsv/{contest_id}"
    )
    response = session.get(url_contest_csv)
    logger.debug(response.status_code)
    logger.debug(response.url)
    logger.debug(response.headers["Content-Type"])

    if "text/html" in response.headers["Content-Type"]:
        logger.warning("We cannot do anything with html!")
        return None

    # if headers say file is a CSV file
    if response.headers["Content-Type"] == "text/csv":
        # write working cookies
        with open("pickled_cookies_works.txt", "wb") as fp:
            pickle.dump(session.cookies, fp)
        # decode bytes into string
        # csvfile = response.content.decode("utf-8")
        csvfile = response.content.decode("utf-8-sig")
        print(csvfile, file=open(f"contest-standings-{contest_id}.csv", "w"))
        # open reader object on csvfile
        # rdr = csv.reader(csvfile.splitlines(), delimiter=",")
        return list(csv.reader(csvfile.splitlines(), delimiter=","))

    # write working cookies
    with open("pickled_cookies_works.txt", "wb") as fp:
        pickle.dump(session.cookies, fp)
    # request will be a zip file
    zipz = zipfile.ZipFile(io.BytesIO(response.content))
    for name in zipz.namelist():
        # extract file - it seems easier this way
        path = zipz.extract(name)
        logger.debug("path: %s", path)
        with zipz.open(name) as csvfile:
            logger.debug("name within zipfile: %s", name)
            # convert to TextIOWrapper object
            lines = io.TextIOWrapper(csvfile, encoding="utf-8", newline="\n")
            # open reader object on csvfile within zip file
            # rdr = csv.reader(lines, delimiter=",")
            return list(csv.reader(lines, delimiter=","))


def cj_from_pickle(filename):
    try:
        with open(filename, "rb") as fp:
            return pickle.load(fp)
    except FileNotFoundError as err:
        logger.error("File %s not found [%s]", filename, err)
        return False


def db_get_live_contest(conn, sport, entry_fee=25):
    # get cursor
    cur = conn.cursor()

    try:
        # execute SQL command
        sql = (
            "SELECT dk_id, name, draft_group, positions_paid "
            "FROM contests "
            "WHERE sport=? "
            "  AND entry_fee=? "
            "  AND start_date <= datetime('now', 'localtime') "
            # "  AND status='LIVE' "
            "  AND completed=0 "
            "ORDER BY entries DESC "
            "LIMIT 1"
        )

        cur.execute(sql, (sport, entry_fee))

        # fetch rows
        row = cur.fetchone()

        if row:
            # return none if contest has not started yet
            # start_date = datetime.datetime.strptime(row[2], "%Y-%m-%d %H:%M:%S")
            # if now < start_date:
            #     logger.debug(
            #         "Contest {} has not started yet start_date: {}".format(
            #             row[0], start_date
            #         )
            #     )
            #     return None

            # return dk_id, draft_group
            # return row[:2]
            return row

        return None

    except sqlite3.Error as err:
        logger.error("sqlite error in get_live_contest(): %s", err.args[0])


def main():
    """Use database and update Google Sheet with contest standings from DraftKings."""
    # parse arguments
    parser = argparse.ArgumentParser()
    choices = [
        "NBA",
        "NFL",
        "CFB",
        "GOLF",
        "PGAMain",
        "PGAWeekend",
        "PGAShowdown",
        "NHL",
        "MLB",
        "TEN",
        "XFL",
        "MMA",
        "LOL",
        "NAS",
    ]

    parser.add_argument(
        "-s",
        "--sport",
        choices=choices,
        required=True,
        help="Type of contest (NBA, NFL, GOLF, CFB, NHL, MLB, TEN, XFL, MMA, or LOL)",
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
    # print(args)

    # create connection to database file
    # create_connection("contests.db")
    conn = sqlite3.connect("contests.db")

    now = datetime.datetime.now(timezone("US/Eastern"))

    for sport in args.sport:

        min_entry_fee = 25
        if sport == "CFB":
            min_entry_fee = 5

        result = db_get_live_contest(conn, sport, min_entry_fee)

        if not result:
            logger.warning("There are no live contests for %s! Moving on.", sport)
            continue

        # store dk_id and draft_group from database result
        dk_id, name, draft_group, positions_paid = result

        fn = f"DKSalaries_{sport}_{now:%A}.csv"

        logger.debug(args)

        dk = Draftkings()

        if draft_group:
            logger.info("Downloading salary file (draft_group: %d)", draft_group)
            dk.download_salary_csv(sport, draft_group, fn)

        # pull contest standings from draftkings
        contest_list = pull_contest_zip(dk_id)

        #
        if contest_list is None:
            logger.error("pull_contest_zip() - contest_list is None.")
            continue
        if not contest_list:  # contest_list is empty
            logger.error("pull_contest_zip() - contest_list is empty.")
            continue

        sheet = DFSSheet(sport)

        logger.debug("Creating Results object Results(%s, %s, %s)", sport, dk_id, fn)

        results = Results(sport, dk_id, fn, positions_paid)
        players_to_values = results.players_to_values(sport)
        sheet.clear_standings()
        sheet.write_players(players_to_values)
        sheet.add_contest_details(name, positions_paid)
        logger.info("Writing players to sheet")
        sheet.add_last_updated(now)

        if results.min_cash_pts > 0:
            sheet.add_min_cash(results.min_cash_pts)

        if args.nolineups and results.vip_list:
            logger.info("Writing vip_lineups to sheet")
            sheet.clear_lineups()
            sheet.write_vip_lineups(results.vip_list)


if __name__ == "__main__":
    main()
