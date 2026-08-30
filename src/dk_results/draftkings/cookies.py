import logging
import os
import pickle
import subprocess
import sys
import tempfile
from collections.abc import Iterable
from http.cookiejar import Cookie, LoadError, MozillaCookieJar
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from requests.cookies import RequestsCookieJar

from dk_results.paths import repo_file

load_dotenv()

logger = logging.getLogger(__name__)

PICKLE_FILE = str(repo_file("pickled_cookies_works.txt"))


def _cookie_to_dict(cookie: Cookie) -> dict[str, Any]:
    return {
        "name": cookie.name,
        "value": cookie.value,
        "domain": cookie.domain,
        "path": cookie.path,
        "expires": cookie.expires or None,
        "secure": cookie.secure,
    }


def _cookie_matches_domain(cookie: Cookie, domain: str) -> bool:
    cookie_domain = cookie.domain.lstrip(".").lower()
    requested_domain = domain.lstrip(".").lower()
    return cookie_domain == requested_domain or cookie_domain.endswith(f".{requested_domain}")


def _profile_path() -> str | None:
    db_path = os.getenv("COOKIES_DB_PATH")
    if not db_path:
        return None
    path = Path(db_path).expanduser()
    if path.name == "Cookies":
        return str(path.parent)
    return str(path)


def _yt_dlp_failure_message(result: subprocess.CompletedProcess[str]) -> str:
    """Turn known yt-dlp failures into actionable, non-sensitive messages."""
    stderr = (result.stderr or "").lower()
    if "no module named" in stderr and "yt_dlp" in stderr:
        return "yt-dlp is not installed"
    if "could not find" in stderr and "cookies database" in stderr:
        return "browser cookie database was not found"
    if any(marker in stderr for marker in ("cannot decrypt", "failed to decrypt", "no key found", "keyring")):
        return "browser cookies could not be decrypted; check browser keyring access"
    return f"yt-dlp failed to export browser cookies (exit code {result.returncode})"


def _export_browser_cookies(browser_spec: str, cookie_file: Path) -> None:
    """Export browser cookies to a temporary Netscape-format file."""
    try:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "yt_dlp",
                "--ignore-errors",
                "--simulate",
                "--cookies-from-browser",
                browser_spec,
                "--cookies",
                str(cookie_file),
                "https://www.draftkings.com/",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        logger.error("could not start yt-dlp: %s", type(exc).__name__)
        raise RuntimeError("could not start yt-dlp; check the project environment") from exc

    if not cookie_file.exists():
        message = _yt_dlp_failure_message(result)
        logger.error(message)
        raise RuntimeError(message)


def _load_exported_cookies(cookie_file: Path) -> list[Cookie]:
    """Load cookies from a yt-dlp Netscape-format export."""
    jar = MozillaCookieJar(str(cookie_file))
    try:
        jar.load(ignore_discard=True, ignore_expires=True)
    except (LoadError, OSError, ValueError) as exc:
        logger.error("yt-dlp produced an invalid browser cookie export: %s", type(exc).__name__)
        raise RuntimeError("yt-dlp produced an invalid browser cookie export") from exc
    return list(jar)


def _filter_cookies(cookies: Iterable[Cookie], domains: list[str]) -> list[dict[str, Any]]:
    """Convert cookies whose domains match the requested domains."""
    return [
        _cookie_to_dict(cookie)
        for cookie in cookies
        if any(_cookie_matches_domain(cookie, domain) for domain in domains)
    ]


def get_rookie_cookies(domains: list[str] | None = None) -> list[dict[str, Any]]:
    """Get DraftKings cookies from the configured browser using yt-dlp."""
    if domains is None:
        domains = ["draftkings.com"]

    platform = os.getenv("DK_PLATFORM", "pi").lower()
    browser = "chromium" if platform == "pi" else "chrome"
    profile = _profile_path()
    browser_spec = f"{browser}:{profile}" if profile else browser

    with tempfile.TemporaryDirectory(prefix="dk-yt-dlp-") as temp_dir:
        cookie_file = Path(temp_dir) / "cookies.txt"
        _export_browser_cookies(browser_spec, cookie_file)
        exported_cookies = _load_exported_cookies(cookie_file)

    cookies = _filter_cookies(exported_cookies, domains)
    if not cookies:
        raise RuntimeError("yt-dlp exported no cookies for the requested domains")
    return cookies


def cookies_to_dict(cookies: Iterable[dict[str, Any]]) -> dict[str, str]:
    """Convert browser cookies to a simple {name: value} dict."""
    return {cookie["name"]: cookie["value"] for cookie in cookies}


def cookies_to_jar(cookies: Iterable[dict[str, Any]]) -> RequestsCookieJar:
    """Convert browser cookies to RequestsCookieJar."""
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
    path = Path(filename)
    if not path.is_absolute():
        path = repo_file(filename)
    if path.exists():
        try:
            with path.open("rb") as f:
                return pickle.load(f)
        except Exception as e:
            logger.warning(f"Failed to load pickled cookies: {e}")
    return None


def save_cookies_to_pickle(cookies: Iterable[dict[str, Any]], filename: str = PICKLE_FILE) -> None:
    """Save cookies to pickle file."""
    path = Path(filename)
    if not path.is_absolute():
        path = repo_file(filename)
    try:
        with path.open("wb") as f:
            pickle.dump(cookies, f)
    except Exception as e:
        logger.error(f"Failed to save cookies: {e}")


def get_dk_cookies(
    use_pickle: bool = False, domains: list[str] | None = None
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
