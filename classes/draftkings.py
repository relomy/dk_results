"""Creating a Draftkings object which can fetch contest results (authenticated)
       and salary files for contests (unauthenticated).
    """
import logging

import browsercookie
import requests

# load the logging configuration
logging.config.fileConfig("logging.ini")


class Draftkings:
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
            self.logger.debug("CONTEST_TYPES [%s]: %s", sport, CONTEST_TYPES[sport])

        csv_url = "https://www.draftkings.com/lineup/getavailableplayerscsv?contestTypeId={0}&draftGroupId={1}".format(
            CONTEST_TYPES[sport], draft_group
        )
        # send GET request
        response = self.s.get(csv_url)

        # if not successful, raise an exception
        if response.status_code != 200:
            raise Exception(
                "Requests status != 200. It is: {0}".format(response.status_code)
            )

        # dump html to file to avoid multiple requests
        with open(filename, "w") as outfile:
            self.logger.debug("Writing r.text to %s", filename)
            print(response.text, file=outfile)
