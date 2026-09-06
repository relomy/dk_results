import logging
import pickle

import requests
from requests.cookies import RequestsCookieJar

from .cookies import get_dk_cookies

logger = logging.getLogger(__name__)


class AuthSession:
    """Create and hold an authenticated DraftKings requests.Session, lazily."""

    def __init__(self) -> None:
        self.session: requests.Session | None = None

    def get_session(self) -> requests.Session:
        """Return the configured requests session, extracting cookies on first use."""
        if self.session is None:
            _, cookies = get_dk_cookies(use_pickle=True)
            self.session = self.setup_session(cookies)
        return self.session

    def cj_from_pickle(self, filename: str) -> RequestsCookieJar | None:
        """Load a RequestsCookieJar from a pickle file if present."""
        try:
            with open(filename, "rb") as fp:
                return pickle.load(fp)
        except FileNotFoundError as err:
            logger.error("File %s not found [%s]", filename, err)
            return None

    def setup_session(self, cookies: RequestsCookieJar) -> requests.Session:
        """Create a requests.Session and populate it with cookies."""
        session = requests.Session()

        for cookie in cookies:
            # if the cookies already exists from a legitimate fresh session, clear them out
            if cookie.name in session.cookies:
                logger.debug("removing %s from 'cookies'", cookie.name)
                cookies.clear(cookie.domain, cookie.path, cookie.name)
            else:
                if not cookie.expires:
                    continue

        logger.debug("adding all missing cookies to session.cookies")
        session.cookies.update(cookies)

        return session
