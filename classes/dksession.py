import logging
import logging.config
import pickle

import requests

from classes.cookieservice import get_dk_cookies

# load the logging configuration
logging.config.fileConfig("logging.ini")
logger = logging.getLogger(__name__)


class DkSession:
    def __init__(self) -> None:
        _, cookies = get_dk_cookies()
        self.session = self.setup_session(cookies)

    def get_session(self):
        return self.session

    def cj_from_pickle(self, filename):
        try:
            with open(filename, "rb") as fp:
                return pickle.load(fp)
        except FileNotFoundError as err:
            logger.error("File %s not found [%s]", filename, err)
            return False

    def setup_session(self, cookies):
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

        return session
