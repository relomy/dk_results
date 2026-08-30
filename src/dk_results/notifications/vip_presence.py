"""The VIP-presence oracle and its DraftKings read seam.

`VipPresence` answers one question: is a tracked VIP entered in a contest? It
returns a *presence verdict* — ``present`` / ``absent`` / ``unknown`` /
``unknown_capped`` — reading entrants through a narrow `ContestResultsPort`
and caching verdicts through `NotificationStore`. It refreshes ``absent`` on
the existing policy, short-circuiting the moment any tracked VIP is found
rather than enumerating everyone entered. ``unknown_capped`` is returned
specifically when the entrant-page cap is hit before a conclusive answer (a
structural fact about the field size, not a resolved verdict); every other
inconclusive read (an ambiguous parse, a failed request, no VIPs configured)
is the plain ``unknown``.

It is a pure verdict provider: no announcement or suppression logic lives
here. Suppression is the processor's job, and it applies two different
policies depending on the milestone — see `CompletionProcessor`. Per ADR
0001, `ContestResultsPort` is the completion workflow's own DraftKings slice,
separate from `SportProcessor`'s `DkPort`.
"""

from __future__ import annotations

import datetime
import logging
import re
from typing import Any, Protocol

import requests

from dk_results.persistence.notification_store import NotificationStore

logger = logging.getLogger(__name__)

# Presence verdicts.
VIP_PRESENT = "present"
VIP_ABSENT = "absent"
VIP_UNKNOWN = "unknown"
# A structural variant of VIP_UNKNOWN: the entrant-page cap was hit before a
# conclusive answer, so the field is simply too large to fully scan — distinct
# from a transient failure, since re-checking later won't resolve it either.
VIP_UNKNOWN_CAPPED = "unknown_capped"

# Policy knobs (preserved from the original free functions).
VIP_ABSENT_REFRESH_MINUTES = 10
VIP_ENTRANT_PAGE_LIMIT = 50

_ENTRANT_USERNAME_RE = re.compile(r"""data-un\s*=\s*['"]([^'"]+)['"]""", re.IGNORECASE)


class ContestResultsPort(Protocol):
    """The DraftKings readouts the completion workflow needs, keyed by contest id."""

    def get_contest_detail(self, dk_id: int, timeout: int | None = None) -> dict[str, Any]: ...
    def get_contest_entrants_page(
        self,
        contest_id: int,
        page_no: int,
        timeout: int | None = None,
        session: requests.Session | None = None,
    ) -> str: ...
    def get_leaderboard(
        self,
        contest_id: int,
        timeout: int | None = None,
        session: requests.Session | None = None,
    ) -> dict[str, Any]: ...


def vip_key(name: Any) -> str:
    """Normalize a VIP name for case-insensitive matching."""
    if not isinstance(name, str):
        return ""
    return name.strip().lower()


def _parse_entrant_usernames(html: str) -> list[str]:
    """Extract normalized entrant usernames from an entrants-page fragment."""
    if not html:
        return []
    return [match.strip().lower() for match in _ENTRANT_USERNAME_RE.findall(html) if match.strip()]


def _entrant_payload_is_ambiguous(html: str, entrants: list[str]) -> bool:
    """True when a page mentions entrants but none parsed — an unreliable read."""
    if entrants:
        return False
    lowered = html.lower()
    return "data-un" in lowered


def _parse_dt(value: Any) -> datetime.datetime | None:
    if not value:
        return None
    if isinstance(value, datetime.datetime):
        return value
    try:
        return datetime.datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _should_refresh_absent(checked_at: str, start_date: str) -> bool:
    """Whether a cached ``absent`` verdict is stale enough to re-check."""

    def _normalize_local(dt: datetime.datetime) -> datetime.datetime:
        local_tz = datetime.datetime.now().astimezone().tzinfo
        if dt.tzinfo is None:
            return dt.replace(tzinfo=local_tz)
        return dt.astimezone(local_tz)

    checked_dt = _parse_dt(checked_at)
    start_dt = _parse_dt(start_date)
    if not checked_dt or not start_dt:
        return True

    checked_local = _normalize_local(checked_dt)
    start_local = _normalize_local(start_dt)
    now_local = datetime.datetime.now(start_local.tzinfo)
    if now_local < start_local:
        return (now_local - checked_local) >= datetime.timedelta(minutes=VIP_ABSENT_REFRESH_MINUTES)
    return False


class VipPresence:
    """Oracle returning a presence verdict for a contest, cached in `NotificationStore`."""

    def __init__(self, results: ContestResultsPort, store: NotificationStore) -> None:
        self._results = results
        self._store = store

    def verdict(self, dk_id: int, start_date: str, vip_names: list[str]) -> str:
        """Return ``present`` / ``absent`` / ``unknown`` for ``dk_id``.

        Serves a cached ``present`` immediately and a cached ``absent`` until the
        refresh policy allows a re-check, then reads entrant pages until a VIP is
        found (``present``), a page proves the field empty (``absent``), the page
        cap is hit, a page is ambiguous, or a read fails (``unknown``).
        """
        if not vip_names:
            return VIP_UNKNOWN

        vip_keys = {vip_key(name) for name in vip_names if vip_key(name)}
        if not vip_keys:
            return VIP_UNKNOWN

        cached = self._store.get_presence(dk_id)
        if cached:
            cached_status, checked_at = cached
            if cached_status == VIP_PRESENT:
                return VIP_PRESENT
            if cached_status == VIP_ABSENT and not _should_refresh_absent(checked_at, start_date):
                return VIP_ABSENT

        try:
            for page_no in range(1, VIP_ENTRANT_PAGE_LIMIT + 1):
                html = self._results.get_contest_entrants_page(dk_id, page_no)
                entrants = _parse_entrant_usernames(html)
                if _entrant_payload_is_ambiguous(html, entrants):
                    logger.warning("entrant payload parse ambiguity for dk_id=%s page=%s", dk_id, page_no)
                    return VIP_UNKNOWN
                if not entrants:
                    self._store.upsert_presence(dk_id, VIP_ABSENT)
                    return VIP_ABSENT
                if any(name in vip_keys for name in entrants):
                    self._store.upsert_presence(dk_id, VIP_PRESENT)
                    return VIP_PRESENT
        except Exception:
            logger.warning("VIP presence check failed for dk_id=%s", dk_id, exc_info=True)
            return VIP_UNKNOWN

        logger.info("vip presence page cap hit for dk_id=%s; returning unknown_capped", dk_id)
        return VIP_UNKNOWN_CAPPED
