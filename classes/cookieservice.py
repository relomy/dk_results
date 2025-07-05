import logging
import os
import pickle
from typing import List, Optional

from requests.cookies import RequestsCookieJar
from rookiepy import chrome

logger = logging.getLogger(__name__)

PICKLE_FILE = "pickled_cookies_works.txt"


def get_rookie_cookies(domains: Optional[List[str]] = None):
    """Get cookies from rookiepy for given domains (defaults to draftkings.com)."""
    if domains is None:
        domains = ["draftkings.com"]

    cookies = chrome(domains=domains)
    return cookies


def cookies_to_dict(cookies) -> dict:
    """Convert rookiepy cookies to a simple {name: value} dict."""
    return {cookie["name"]: cookie["value"] for cookie in cookies}


def cookies_to_jar(cookies) -> RequestsCookieJar:
    """Convert rookiepy cookies to RequestsCookieJar."""
    jar = RequestsCookieJar()
    for cookie in cookies:
        jar.set(
            cookie["name"],
            cookie["value"],
            domain=cookie.get("domain"),
            path=cookie.get("path", "/"),
        )
    return jar


def load_cookies_from_pickle(filename: str = PICKLE_FILE):
    """Load pickled cookies if file exists."""
    if os.path.exists(filename):
        try:
            with open(filename, "rb") as f:
                return pickle.load(f)
        except Exception as e:
            logger.warning(f"Failed to load pickled cookies: {e}")
    return None


def save_cookies_to_pickle(cookies, filename: str = PICKLE_FILE):
    """Save cookies to pickle file."""
    try:
        with open(filename, "wb") as f:
            pickle.dump(cookies, f)
    except Exception as e:
        logger.error(f"Failed to save cookies: {e}")


def get_dk_cookies(use_pickle=False, domains=None):
    """High-level method to get DK cookies (dict + jar), optionally from pickle."""
    cookies = None
    if use_pickle:
        cookies = load_cookies_from_pickle()

    if not cookies:
        cookies = get_rookie_cookies(domains)
        if use_pickle:
            save_cookies_to_pickle(cookies)

    return cookies_to_dict(cookies), cookies_to_jar(cookies)
