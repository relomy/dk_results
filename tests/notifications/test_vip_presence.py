import datetime
import sqlite3

import pytest

from dk_results.draftkings.draftkings import Draftkings
from dk_results.notifications.vip_presence import (
    VIP_ABSENT,
    VIP_ENTRANT_PAGE_LIMIT,
    VIP_PRESENT,
    VIP_UNKNOWN,
    ContestResultsPort,
    VipPresence,
    _entrant_payload_is_ambiguous,
    _parse_entrant_usernames,
    _should_refresh_absent,
    vip_key,
)
from dk_results.persistence.notification_store import NotificationStore


def _page(*usernames: str) -> str:
    return "".join(f'<div data-un="{name}"></div>' for name in usernames)


class FakeResultsPort:
    """Canned `ContestResultsPort` returning per-page entrant HTML."""

    def __init__(self, pages: dict[int, str] | None = None, *, default: str = "", raises: bool = False) -> None:
        self._pages = pages or {}
        self._default = default
        self._raises = raises
        self.entrant_calls: list[int] = []

    def get_contest_entrants_page(self, contest_id, page_no, timeout=None, session=None) -> str:
        self.entrant_calls.append(page_no)
        if self._raises:
            raise RuntimeError("boom")
        return self._pages.get(page_no, self._default)

    def get_contest_detail(self, dk_id, timeout=None):  # pragma: no cover - unused in these tests
        return {}

    def get_leaderboard(self, contest_id, timeout=None, session=None):  # pragma: no cover - unused
        return {}


@pytest.fixture
def store():
    conn = sqlite3.connect(":memory:")
    try:
        yield NotificationStore(conn)
    finally:
        conn.close()


def _seed_presence(store: NotificationStore, dk_id: int, status: str, checked_at: str) -> None:
    """Write a presence row with an explicit ``checked_at`` (bypassing the clock)."""
    store._conn.execute(
        "INSERT INTO contest_vip_presence (dk_id, status, checked_at) VALUES (?, ?, ?)",
        (dk_id, status, checked_at),
    )
    store._conn.commit()


def test_draftkings_satisfies_contest_results_port():
    port: type[ContestResultsPort] = Draftkings
    for method in ("get_contest_detail", "get_contest_entrants_page", "get_leaderboard"):
        assert callable(getattr(port, method))


def test_no_vip_names_is_unknown(store):
    port = FakeResultsPort()
    assert VipPresence(port, store).verdict(1, "2026-01-01T00:00:00", []) == VIP_UNKNOWN
    assert port.entrant_calls == []


def test_blank_vip_names_is_unknown(store):
    port = FakeResultsPort()
    assert VipPresence(port, store).verdict(1, "2026-01-01T00:00:00", ["", "   "]) == VIP_UNKNOWN
    assert port.entrant_calls == []


def test_vip_on_first_page_is_present_and_cached(store):
    port = FakeResultsPort({1: _page("someoneelse", "VipGuy")})
    verdict = VipPresence(port, store).verdict(1, "2026-01-01T00:00:00", ["VipGuy"])
    assert verdict == VIP_PRESENT
    assert store.get_presence(1)[0] == VIP_PRESENT


def test_vip_found_on_later_page(store):
    port = FakeResultsPort({1: _page("nope"), 2: _page("vipguy")})
    verdict = VipPresence(port, store).verdict(1, "2026-01-01T00:00:00", ["VipGuy"])
    assert verdict == VIP_PRESENT
    assert port.entrant_calls == [1, 2]


def test_empty_page_is_absent_and_cached(store):
    port = FakeResultsPort({1: ""})
    verdict = VipPresence(port, store).verdict(1, "2026-01-01T00:00:00", ["VipGuy"])
    assert verdict == VIP_ABSENT
    assert store.get_presence(1)[0] == VIP_ABSENT


def test_ambiguous_payload_is_unknown_and_not_cached(store):
    # Mentions data-un but nothing parses — an unreliable read.
    port = FakeResultsPort({1: "<div data-un=></div>"})
    verdict = VipPresence(port, store).verdict(1, "2026-01-01T00:00:00", ["VipGuy"])
    assert verdict == VIP_UNKNOWN
    assert store.get_presence(1) is None


def test_page_cap_is_unknown(store):
    port = FakeResultsPort(default=_page("rando"))
    verdict = VipPresence(port, store).verdict(1, "2026-01-01T00:00:00", ["VipGuy"])
    assert verdict == VIP_UNKNOWN
    assert port.entrant_calls == list(range(1, VIP_ENTRANT_PAGE_LIMIT + 1))


def test_read_failure_is_unknown(store):
    port = FakeResultsPort(raises=True)
    verdict = VipPresence(port, store).verdict(1, "2026-01-01T00:00:00", ["VipGuy"])
    assert verdict == VIP_UNKNOWN


def test_cached_present_short_circuits(store):
    _seed_presence(store, 1, VIP_PRESENT, "2026-01-01T00:00:00")
    port = FakeResultsPort(raises=True)  # would blow up if consulted
    verdict = VipPresence(port, store).verdict(1, "2026-01-01T00:00:00", ["VipGuy"])
    assert verdict == VIP_PRESENT
    assert port.entrant_calls == []


def test_cached_absent_served_within_refresh_window(store):
    # Contest starts in the future; absent was checked just now → do not re-check.
    now = datetime.datetime.now().isoformat()
    future = (datetime.datetime.now() + datetime.timedelta(hours=2)).isoformat()
    _seed_presence(store, 1, VIP_ABSENT, now)
    port = FakeResultsPort(raises=True)
    verdict = VipPresence(port, store).verdict(1, future, ["VipGuy"])
    assert verdict == VIP_ABSENT
    assert port.entrant_calls == []


def test_cached_absent_refreshes_when_stale(store):
    # Absent checked long ago and contest still upcoming → re-check the port.
    stale = (datetime.datetime.now() - datetime.timedelta(minutes=30)).isoformat()
    future = (datetime.datetime.now() + datetime.timedelta(hours=2)).isoformat()
    _seed_presence(store, 1, VIP_ABSENT, stale)
    port = FakeResultsPort({1: _page("vipguy")})
    verdict = VipPresence(port, store).verdict(1, future, ["VipGuy"])
    assert verdict == VIP_PRESENT
    assert port.entrant_calls == [1]


# ── Helper units (absorbed from the old CLI free functions) ─────────────────────


def test_vip_key_strips_and_lowercases():
    assert vip_key("  VipUser  ") == "vipuser"


def test_vip_key_non_string_returns_empty():
    assert vip_key(None) == ""
    assert vip_key(123) == ""


def test_parse_entrant_usernames_accepts_single_or_double_quotes():
    html = "<td data-un='vip_alpha'></td><td data-un=\"vip_beta\"></td>"
    assert _parse_entrant_usernames(html) == ["vip_alpha", "vip_beta"]


def test_parse_entrant_usernames_empty_and_no_match():
    assert _parse_entrant_usernames("") == []
    assert _parse_entrant_usernames("<td>no usernames</td>") == []


def test_entrant_payload_ambiguity():
    assert _entrant_payload_is_ambiguous("<td data-un='x'>", ["x"]) is False
    assert _entrant_payload_is_ambiguous("<td data-un=''>", []) is True
    assert _entrant_payload_is_ambiguous("<td>no attrs</td>", []) is False


def test_should_refresh_absent_normalizes_timezone_before_subtraction():
    now_local = datetime.datetime.now().astimezone().replace(microsecond=0)
    checked_at = (now_local - datetime.timedelta(minutes=11)).replace(tzinfo=None).isoformat(sep=" ")
    start_date = (now_local + datetime.timedelta(minutes=30)).astimezone(datetime.timezone.utc).isoformat()
    assert _should_refresh_absent(checked_at, start_date) is True


def test_should_refresh_absent_is_sticky_after_start():
    now_local = datetime.datetime.now().replace(microsecond=0)
    checked_at = (now_local - datetime.timedelta(minutes=30)).isoformat(sep=" ")
    start_date = (now_local - datetime.timedelta(minutes=1)).isoformat(sep=" ")
    assert _should_refresh_absent(checked_at, start_date) is False
