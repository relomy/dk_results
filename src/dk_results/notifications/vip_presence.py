"""The VIP-presence oracle and its DraftKings/standings read seams.

`VipPresence` answers one question: is a tracked VIP entered in a contest? It
returns a *presence verdict* — ``present`` / ``absent`` / ``unknown`` /
``unknown_capped`` — caching verdicts through `NotificationStore`. Per
ADR-0012, it consults the standings poll `SportProcessor` already persists
first (via the narrow `StandingsPresencePort`) and only falls back to
reading entrants through `ContestResultsPort` when nothing has been polled
yet for that contest. The entrant-page fallback refreshes ``absent`` on the
existing policy, short-circuiting the moment any tracked VIP is found rather
than enumerating everyone entered. ``unknown_capped`` is returned
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

from dk_results.persistence.contestdatabase import VipCashStatus
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


class StandingsPresencePort(Protocol):
    """The standings-poll readouts VIP presence needs, keyed by contest id (ADR-0012)."""

    def get_standings_polled_at(self, dk_id: int) -> datetime.datetime | None: ...
    def get_vip_cash_status(self, dk_id: int) -> list[VipCashStatus]: ...


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

    def __init__(
        self,
        results: ContestResultsPort,
        store: NotificationStore,
        standings: StandingsPresencePort | None = None,
    ) -> None:
        self._results = results
        self._store = store
        self._standings = standings

    def verdict(self, dk_id: int, start_date: str, vip_names: list[str]) -> str:
        """Return ``present`` / ``absent`` / ``unknown`` for ``dk_id``.

        Checks the standings poll first (ADR-0012): once a contest has been
        polled, the standings answer is authoritative in both directions and
        the entrant-page scan below is skipped entirely. Otherwise, serves a
        cached ``present`` immediately and a cached ``absent`` until the
        refresh policy allows a re-check, then reads entrant pages until a VIP
        is found (``present``), a page proves the field empty (``absent``),
        the page cap is hit, a page is ambiguous, or a read fails (``unknown``).
        """
        if not vip_names:
            return VIP_UNKNOWN

        vip_keys = {vip_key(name) for name in vip_names if vip_key(name)}
        if not vip_keys:
            return VIP_UNKNOWN

        standings_verdict = self._standings_verdict(dk_id, vip_keys)
        if standings_verdict is not None:
            return standings_verdict

        return self._entrant_scan_verdict(dk_id, start_date, vip_keys)

    def _entrant_scan_verdict(self, dk_id: int, start_date: str, vip_keys: set[str]) -> str:
        """The pre-ADR-0012 fallback: cached-then-live entrant-page scan."""
        cached_verdict = self._cached_entrant_verdict(dk_id, start_date)
        if cached_verdict is not None:
            return cached_verdict
        return self._live_entrant_scan(dk_id, vip_keys)

    def _cached_entrant_verdict(self, dk_id: int, start_date: str) -> str | None:
        """A still-fresh cached verdict from a prior entrant-page scan, if any."""
        cached = self._store.get_presence(dk_id)
        if not cached:
            return None
        cached_status, checked_at = cached
        if cached_status == VIP_PRESENT:
            return VIP_PRESENT
        if cached_status == VIP_ABSENT and not _should_refresh_absent(checked_at, start_date):
            return VIP_ABSENT
        return None

    def _live_entrant_scan(self, dk_id: int, vip_keys: set[str]) -> str:
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

    def present_vips(self, dk_id: int, vip_names: list[str]) -> list[str]:
        """Return the tracked VIP names the standings poll found entered in ``dk_id``.

        Standings-only (ADR-0012): the entrant-page scan short-circuits at the
        first match by design, so it can never answer "which VIPs," only "at
        least one." Returns ``[]`` when nothing has been polled yet, or when
        no standings source is configured.
        """
        vip_keys = {vip_key(name) for name in vip_names if vip_key(name)}
        if not vip_keys:
            return []
        return self._matching_vip_names(dk_id, vip_keys) or []

    def _standings_verdict(self, dk_id: int, vip_keys: set[str]) -> str | None:
        """Return ``present``/``absent`` from the standings poll, or ``None`` if unpolled.

        A standings-derived ``present`` writes through to `NotificationStore`,
        matching the existing invariant that a cached ``present`` is
        permanent. A standings-derived ``absent`` is not cached — the
        entrant-scan's cached ``absent`` carries a refresh timer sized for the
        cost of re-scanning, which the standings answer has no need of, and
        caching it anyway would plant a second, timer-less ``absent`` in the
        same store under an unrelated policy.
        """
        matching = self._matching_vip_names(dk_id, vip_keys)
        if matching is None:
            return None
        if matching:
            self._store.upsert_presence(dk_id, VIP_PRESENT)
            return VIP_PRESENT
        return VIP_ABSENT

    def _matching_vip_names(self, dk_id: int, vip_keys: set[str]) -> list[str] | None:
        """Tracked VIP names the standings poll found, or ``None`` if unpolled/unconfigured."""
        if self._standings is None:
            return None
        if self._standings.get_standings_polled_at(dk_id) is None:
            return None
        statuses = self._standings.get_vip_cash_status(dk_id)
        return [status.vip_name for status in statuses if vip_key(status.vip_name) in vip_keys]
