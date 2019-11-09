"""Use contest ID to update Google Sheet with DFS results.

Example export CSV/ZIP link
https://www.draftkings.com/contest/exportfullstandingscsv/62753724

Example salary CSV link
https://www.draftkings.com/lineup/getavailableplayerscsv?contestTypeId=70&draftGroupId=22401
12 = MLB 21 = NFL 9 = PGA 24 = NASCAR 10 = Soccer 13 = MMA
"""

import argparse
import csv
import datetime
import io
from os import getenv
import logging
import logging.config
import pickle
import time
import zipfile

import browsercookie
import requests
import selenium.webdriver.chrome.service as chrome_service
from pytz import timezone
from selenium import webdriver

from classes.dfssheet import DFSSheet
from classes.results import Results
from classes.draftkings import Draftkings

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
    # for c in cookies:
    #     if "draft" not in c.domain:
    #         cookies.clear(c.domain, c.path, c.name)
    #     else:
    #         if c.expires:
    #             # chrome is ridiculous - this math is required
    #             new_expiry = c.expires / 1000000
    #             new_expiry -= 11644473600
    #             c.expires = new_expiry

    result = setup_session(contest_id, cookies)
    logger.debug("type(result): {}".format(type(result)))

    if result:
        return result

    # use selenium to refresh cookies
    use_selenium(contest_id)

    # try browsercookie method again
    cookies = browsercookie.chrome()

    # for c in cookies:
    #     if "draft" not in c.domain:
    #         cookies.clear(c.domain, c.path, c.name)
    #     else:
    #         if c.expires:
    #             # chrome is ridiculous - this math is required
    #             # Devide the actual timestamp (in my case it's expires_utc column in cookies table) by 1000000 // And someone should explain my why.
    #             # Subtract 11644473600
    #             # DONE! Now you got UNIX timestamp
    #             new_expiry = c.expires / 1000000
    #             new_expiry -= 11644473600
    #             c.expires = new_expiry

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

            # try:
            # if c.expires <= now.timestamp():
            #     pass
            # logger.debug(
            #     "c.name {} has EXPIRED!!! (c.expires: {} now: {})".format(
            #         c.name, datetime.datetime.fromtimestamp(c.expires), now
            #     )
            # )
            # else:  # check if
            # delta_hours = 5
            # d = datetime.datetime.fromtimestamp(c.expires) - datetime.timedelta(
            #     hours=delta_hours
            # )
            # within 5 hours
            # if d <= now:
            #     pass
            # logger.debug(
            #     "c.name {} expires within {} hours!! difference: {} (c.expires: {} now: {})".format(
            #         c.name,
            #         delta_hours,
            #         datetime.datetime.fromtimestamp(c.expires) - now,
            #         datetime.datetime.fromtimestamp(c.expires),
            #         now,
            #     )
            # )
            # some cookies have unnecessarily long expiration times which produce overflow errors
            # except OverflowError as e:
            #     pass
            # logger.debug(
            #     "Overflow on {} {} [error: {}]".format(c.name, c.expires, e)
            # )

    # exit()
    logger.debug("adding all missing cookies to session.cookies")
    # print(cookies)
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


def main():
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
        "-i", "--id", type=int, required=True, help="Contest ID from DraftKings"
    )
    parser.add_argument("-c", "--csv", help="Slate CSV from DraftKings")
    parser.add_argument(
        "-s",
        "--sport",
        choices=choices,
        required=True,
        help="Type of contest (NBA, NFL, PGAMain, PGAWeekend, PGAShowdown, CFB, NHL, or MLB)",
    )
    parser.add_argument(
        "--nolineups",
        dest="nolineups",
        action="store_false",
        help="If true, will not print VIP lineups",
    )
    parser.add_argument("-v", "--verbose", help="Increase verbosity")
    args = parser.parse_args()

    now = datetime.datetime.now(timezone("US/Eastern"))

    if args.csv:
        fn = args.csv
    else:
        fn = f"DKSalaries_{args.sport}_{now:%A}.csv"

    logger.debug(args)

    dk = Draftkings()

    # pull contest standings from draftkings
    contest_list = pull_contest_zip(args.id)

    if contest_list is None:
        raise Exception("pull_contest_zip() - contest_list is None.")
    elif not contest_list:  # contest_list is empty
        raise Exception("pull_contest_zip() - contest_list is empty.")

    sheet = DFSSheet(args.sport)

    logger.debug(f"Creating Results object Results({args.sport}, {args.id}, fn)")
    r = Results(args.sport, args.id, fn)
    z = r.players_to_values(args.sport)
    sheet.write_players(z)
    logger.info("Writing players to sheet")
    sheet.add_last_updated(now)

    if args.nolineups and r.vip_list:
        logger.info("Writing vip_lineups to sheet")
        sheet.write_vip_lineups(r.vip_list)

    # for u in r.vip_list:
    # logger.info("User: {}".format(u.name))
    # logger.info("User: {}".format(u))
    # logger.info("Lineup:")
    # for p in u.lineup:
    #     logger.debug(p)

    # sheet = DFSsheet("TEN")


if __name__ == "__main__":
    logger = logging.getLogger(__name__)
    main()
