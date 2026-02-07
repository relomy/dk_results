from collections.abc import Callable, Mapping
from typing import Any, Type

import requests
from requests.cookies import RequestsCookieJar

from classes.draftkings import Draftkings
from classes.sport import Sport
from lobby.parsing import get_contests_from_response, get_draft_groups_from_response

LOBBY_URL_TEMPLATE = "https://www.draftkings.com/lobby/getcontests?sport={sport}"

DEFAULT_HEADERS = {
    "Accept": "*/*",
    "Accept-Encoding": "gzip, deflate, sdch",
    "Accept-Language": "en-US,en;q=0.8",
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "Host": "www.draftkings.com",
    "Pragma": "no-cache",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_10_5) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/48.0.2564.97 Safari/537.36"
    ),
    "X-Requested-With": "XMLHttpRequest",
}

FetchJson = Callable[[str, Mapping[str, str], RequestsCookieJar | None], Any]


def requests_fetch_json(
    url: str,
    headers: Mapping[str, str],
    cookies: RequestsCookieJar | None,
) -> Any:
    """Default lobby JSON fetch using requests with existing semantics."""
    return requests.get(url, headers=headers, cookies=cookies).json()


def get_dk_lobby(
    sport: Type[Sport],
    url: str,
    *,
    fetch_json: FetchJson = requests_fetch_json,
    headers: Mapping[str, str] | None = None,
    cookies: RequestsCookieJar | None = None,
) -> tuple[list[dict[str, Any]], list[int], dict[str, Any] | list[Any]]:
    """Get contests + filtered draft groups from DK lobby endpoint."""
    active_headers = headers or DEFAULT_HEADERS
    response = fetch_json(url, active_headers, cookies)
    contests = get_contests_from_response(response)
    draft_groups = get_draft_groups_from_response(response, sport)
    return contests, draft_groups, response


def get_lobby_response(
    sport: str,
    *,
    live: bool = False,
    dk_client: Draftkings | None = None,
) -> dict[str, Any] | list[dict[str, Any]]:
    """Fetch raw lobby response via Draftkings client (used by dkcontests)."""
    client = dk_client or Draftkings()
    return client.get_lobby_contests(sport, live=live)
