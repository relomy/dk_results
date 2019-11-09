import csv
import datetime
import io
import logging
import pickle
import zipfile

import browsercookie
import requests

# load the logging configuration
logging.config.fileConfig("logging.ini")


class Draftkings(object):
    """Creating a Draftkings object which can fetch contest results (authenticated)
       and salary files for contests (unauthenticated).
    """

    def __init__(self, logger=None):
        self.logger = logger or logging.getLogger(__name__)

        self.s = requests.Session()

        # set cookies based on Chrome session
        cookies = browsercookie.chrome()

        # update session with cookies
        self.s.cookies.update(cookies)

    def download_salary_csv(self, sport, draft_group, filename):
        """Given a filename and CSV URL, request download of CSV file and save to filename."""
        CONTEST_TYPES = {
            "PGA": 9,
            "SOC": 10,
            "MLB": 12,
            "NFL": 21,
            "NBA": 70,
            "CFB": 94,
            "TEN": 106,
        }

        if sport in CONTEST_TYPES:
            print("contest_type_id [{}]: {}".format(sport, CONTEST_TYPES[sport]))

        csv_url = "https://www.draftkings.com/lineup/getavailableplayerscsv?contestTypeId={0}&draftGroupId={1}".format(
            CONTEST_TYPES[sport], draft_group
        )
        # send GET request
        r = self.s.get(csv_url)

        # if not successful, raise an exception
        if r.status_code != 200:
            raise Exception("Requests status != 200. It is: {0}".format(r.status_code))

        # dump html to file to avoid multiple requests
        with open(filename, "w") as outfile:
            print("Writing r.text to {}".format(filename))
            print(r.text, file=outfile)

    # def setup_session(self, contest_id, cookies):
    #     now = datetime.datetime.now()

    #     for c in cookies:
    #         # if the cookies already exists from a legitimate fresh session, clear them out
    #         if c.name in s.cookies:
    #             self.logger.debug(
    #                 "removing {} from 'cookies' -- ".format(c.name), end=""
    #             )
    #             cookies.clear(c.domain, c.path, c.name)
    #         else:
    #             if not c.expires:
    #                 continue

    #     logger.debug("adding all missing cookies to session.cookies")
    #     # print(cookies)
    #     self.s.cookies.update(cookies)

    # return request_contest_url(contest_id)

    # def request_contest_url(self, contest_id):
    #     # attempt to GET contest_csv_url
    #     url_contest_csv = (
    #         f"https://www.draftkings.com/contest/exportfullstandingscsv/{contest_id}"
    #     )
    #     r = self.s.get(url_contest_csv)
    #     logger.debug(r.status_code)
    #     logger.debug(r.url)
    #     logger.debug(r.headers["Content-Type"])
    #     # print(r.headers)
    #     if "text/html" in r.headers["Content-Type"]:
    #         logger.info("We cannot do anything with html!")
    #         return None
    #     # if headers say file is a CSV file
    #     elif r.headers["Content-Type"] == "text/csv":
    #         # write working cookies
    #         with open("pickled_cookies_works.txt", "wb") as f:
    #             pickle.dump(s.cookies, f)
    #         # decode bytes into string
    #         csvfile = r.content.decode("utf-8")
    #         print(csvfile, file=open(f"contest-standings-{contest_id}.csv", "w"))
    #         # open reader object on csvfile
    #         # rdr = csv.reader(csvfile.splitlines(), delimiter=",")
    #         return list(csv.reader(csvfile.splitlines(), delimiter=","))
    #     else:
    #         # write working cookies
    #         with open("pickled_cookies_works.txt", "wb") as f:
    #             pickle.dump(s.cookies, f)
    #         # request will be a zip file
    #         z = zipfile.ZipFile(io.BytesIO(r.content))
    #         for name in z.namelist():
    #             # extract file - it seems easier this way
    #             path = z.extract(name)
    #             logger.debug(f"path: {path}")
    #             with z.open(name) as csvfile:
    #                 logger.debug("name within zipfile: {}".format(name))
    #                 # convert to TextIOWrapper object
    #                 lines = io.TextIOWrapper(csvfile, encoding="utf-8", newline="\r\n")
    #                 # open reader object on csvfile within zip file
    #                 # rdr = csv.reader(lines, delimiter=",")
    #                 return list(csv.reader(lines, delimiter=","))
