import logging
import os
import pickle
from typing import Any, Iterable, Optional

from dotenv import load_dotenv
from requests.cookies import RequestsCookieJar
from rookiepy import chrome, chromium_based

load_dotenv()

logger = logging.getLogger(__name__)

PICKLE_FILE = "pickled_cookies_works.txt"


def get_rookie_cookies(domains: Optional[list[str]] = None) -> list[dict[str, Any]]:
    """Get cookies from rookiepy for given domains (defaults to draftkings.com)."""
    if domains is None:
        domains = ["draftkings.com"]

    platform = os.getenv("DK_PLATFORM", "pi").lower()
    db_path = os.getenv("COOKIES_DB_PATH")

    if platform == "pi" and db_path:
        logger.info(f"Loading cookies from Pi chromium db_path: {db_path}")
        cookies = chromium_based(db_path=db_path, domains=domains)
    else:
        logger.info("Using chrome() for macOS or fallback")
        cookies = chrome(domains=domains)

    return cookies


def cookies_to_dict(cookies: Iterable[dict[str, Any]]) -> dict[str, str]:
    """Convert rookiepy cookies to a simple {name: value} dict."""
    return {cookie["name"]: cookie["value"] for cookie in cookies}


def cookies_to_jar(cookies: Iterable[dict[str, Any]]) -> RequestsCookieJar:
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


def load_cookies_from_pickle(
    filename: str = PICKLE_FILE,
) -> RequestsCookieJar | None:
    """Load pickled cookies if file exists."""
    if os.path.exists(filename):
        try:
            with open(filename, "rb") as f:
                return pickle.load(f)
        except Exception as e:
            logger.warning(f"Failed to load pickled cookies: {e}")
    return None


def save_cookies_to_pickle(
    cookies: Iterable[dict[str, Any]], filename: str = PICKLE_FILE
) -> None:
    """Save cookies to pickle file."""
    try:
        with open(filename, "wb") as f:
            pickle.dump(cookies, f)
    except Exception as e:
        logger.error(f"Failed to save cookies: {e}")


def get_dk_cookies(
    use_pickle: bool = False, domains: Optional[list[str]] = None
) -> tuple[dict[str, str], RequestsCookieJar]:
    """High-level method to get DK cookies (dict + jar), optionally from pickle."""
    cookies = None
    if use_pickle:
        cookies = load_cookies_from_pickle()

    if not cookies:
        cookies = get_rookie_cookies(domains)
        if use_pickle:
            save_cookies_to_pickle(cookies)

    return cookies_to_dict(cookies), cookies_to_jar(cookies)
