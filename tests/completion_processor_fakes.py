"""Fakes and builders for the CompletionProcessor characterization tests.

Not a ``test_`` module, so pytest does not collect it. The edge tests that use it
drive ``CompletionProcessor.run(conn)`` with a real in-memory ``ContestDatabase``
and ``NotificationStore`` and fakes only at the DraftKings and Discord edges.
"""

from __future__ import annotations

import datetime
import sqlite3
import sys
import types

from dk_results.completion_processor import CompletionProcessor, CompletionProcessorConfig
from dk_results.persistence.contestdatabase import ContestDatabase
from dk_results.persistence.notification_store import NotificationStore

CONTESTS_TABLE_SQL = """
CREATE TABLE contests (
    dk_id INTEGER PRIMARY KEY,
    sport varchar(10) NOT NULL,
    name varchar(50) NOT NULL,
    start_date datetime NOT NULL,
    draft_group INTEGER NOT NULL,
    total_prizes INTEGER NOT NULL,
    entries INTEGER NOT NULL,
    positions_paid INTEGER,
    entry_fee INTEGER NOT NULL,
    entry_count INTEGER NOT NULL,
    max_entry_count INTEGER NOT NULL,
    completed INTEGER NOT NULL DEFAULT 0,
    status TEXT,
    completed_at TEXT
);
"""


class DummySport:
    name = "NBA"
    sheet_min_entry_fee = 25
    keyword = "%"


def make_sport(name: str, *, fee: int = 25, keyword: str = "%") -> type:
    """A sport class with its own name, minimum entry fee and contest-name keyword."""
    return type(f"{name}Sport", (), {"name": name, "sheet_min_entry_fee": fee, "keyword": keyword})


class RecordingSender:
    """A BonusSenderPort that records everything sent."""

    def __init__(self) -> None:
        self.messages: list[str] = []

    def send_message(self, message: str) -> None:
        self.messages.append(message)


class FixedPresence:
    """A presence oracle returning one canned verdict (``by_id`` overrides it per contest).

    Every query is kept in ``calls`` as ``(dk_id, start_date, vip_names)``.
    """

    def __init__(self, verdict: str, by_id: dict[int, str] | None = None) -> None:
        self._verdict = verdict
        self._by_id = by_id or {}
        self.calls: list[tuple] = []

    def verdict(self, dk_id: int, start_date: str, vip_names: list[str]) -> str:
        self.calls.append((dk_id, start_date, list(vip_names)))
        return self._by_id.get(dk_id, self._verdict)


class StubResults:
    """A ContestResultsPort serving detail payloads (or raising) and one leaderboard.

    ``detail`` may be a list: each call consumes one entry and the last repeats.
    ``details_by_id`` / ``leaderboards_by_id`` override those per contest. A leaderboard
    that is an exception is raised; ``detail_calls`` records every contest id fetched.
    """

    def __init__(
        self,
        *,
        detail=None,
        leaderboard=None,
        detail_error: Exception | None = None,
        details_by_id: dict | None = None,
        leaderboards_by_id: dict | None = None,
    ) -> None:
        self._detail = list(detail) if isinstance(detail, list) else detail
        self._leaderboard = leaderboard
        self._detail_error = detail_error
        self._details_by_id = {k: list(v) if isinstance(v, list) else v for k, v in (details_by_id or {}).items()}
        self._leaderboards_by_id = leaderboards_by_id or {}
        self.detail_calls: list[int] = []

    def get_contest_detail(self, dk_id, timeout=None):
        self.detail_calls.append(dk_id)
        if self._detail_error is not None:
            raise self._detail_error
        source = self._details_by_id.get(dk_id, self._detail)
        if isinstance(source, list):
            source = source.pop(0) if len(source) > 1 else source[0]
        if isinstance(source, Exception):
            raise source
        return source

    def get_leaderboard(self, contest_id, timeout=None, session=None):
        payload = self._leaderboards_by_id.get(contest_id, self._leaderboard)
        if isinstance(payload, Exception):
            raise payload
        return payload

    def get_contest_entrants_page(self, contest_id, page_no, timeout=None, session=None):
        return ""


def detail(*, status: str, positions_paid: int = 10) -> dict:
    return {
        "contestDetail": {
            "payoutSummary": [{"maxPosition": positions_paid}],
            "contestStateDetail": status,
            "maximumEntries": 100,
        }
    }


def leaderboard(*, leader=None, last_winning=None, rows=None) -> dict:
    """A leaderboard payload; each part defaults to a finished (zero time remaining) one."""
    return {
        "leader": {"timeRemaining": 0, "fantasyPoints": 229} if leader is None else leader,
        "lastWinningEntry": {"timeRemaining": 0, "fantasyPoints": 185.5} if last_winning is None else last_winning,
        "leaderBoard": [cashed_row("FooBar")] if rows is None else rows,
    }


def cashed_row(user, *, time_remaining=0, winning_value=100.0) -> dict:
    return {"userName": user, "timeRemaining": time_remaining, "fantasyPoints": 229, "winningValue": winning_value}


def make_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute(CONTESTS_TABLE_SQL)
    conn.commit()
    return conn


def insert_contest(
    conn,
    *,
    dk_id=1,
    name="Contest1",
    start_date="2024-01-01 00:00:00",
    status="UPCOMING",
    completed=0,
    sport="NBA",
    entry_fee=25,
    entries=100,
    draft_group=1,
    positions_paid=None,
):
    conn.execute(
        """
        INSERT INTO contests (
            dk_id, sport, name, start_date, draft_group, total_prizes, entries,
            positions_paid, entry_fee, entry_count, max_entry_count, completed, status
        ) VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?, 0, 1, ?, ?)
        """,
        (dk_id, sport, name, start_date, draft_group, entries, positions_paid, entry_fee, completed, status),
    )
    conn.commit()


def contest_row(conn, dk_id: int = 1) -> tuple:
    """The contest's synced ``(positions_paid, status, completed)``."""
    return conn.execute("SELECT positions_paid, status, completed FROM contests WHERE dk_id=?", (dk_id,)).fetchone()


def stored_events(conn, dk_id: int = 1) -> list[str]:
    """The notification events recorded for a contest, oldest first."""
    rows = conn.execute("SELECT event FROM contest_notifications WHERE dk_id=? ORDER BY rowid", (dk_id,))
    return [event for (event,) in rows]


def freeze_clock(monkeypatch, now: datetime.datetime) -> None:
    """Pin ``datetime.datetime.now()`` for the completion workflow's modules.

    A naive call returns ``now`` as a naive wall time; an aware call converts it (``now``
    must then be aware). Patches every loaded ``dk_results.completion*`` module that
    imports ``datetime``, so it survives the workflow being split across modules.
    """

    class FrozenDatetime(datetime.datetime):
        @classmethod
        def now(cls, tz=None):
            return now.replace(tzinfo=None) if tz is None else now.astimezone(tz)

    shim = types.SimpleNamespace(**{k: getattr(datetime, k) for k in dir(datetime) if not k.startswith("__")})
    shim.datetime = FrozenDatetime
    for name, module in list(sys.modules.items()):
        if name.startswith("dk_results.completion") and getattr(module, "datetime", None) is datetime:
            monkeypatch.setattr(module, "datetime", shim)


def record(conn, dk_id: int, kind: str) -> None:
    NotificationStore(conn).record_notification(dk_id, kind)


def make_processor(
    conn,
    *,
    results,
    sender,
    presence=None,
    vips=None,
    sport_choices=None,
    warning_schedule=None,
    warning_schedules=None,
    default_warning_schedule=None,
    sport_emoji=None,
    spreadsheet_id=None,
    sheet_gid_map=None,
    dashboard_base_url=None,
    notifications_enabled=True,
):
    config = CompletionProcessorConfig(
        sport_choices=sport_choices if sport_choices is not None else {"NBA": DummySport},
        warning_schedules=warning_schedules if warning_schedules is not None else {"default": warning_schedule or []},
        default_warning_schedule=[25] if default_warning_schedule is None else default_warning_schedule,
        sport_emoji=sport_emoji if sport_emoji is not None else {"NBA": "🏀"},
        spreadsheet_id=spreadsheet_id,
        sheet_gid_map=sheet_gid_map or {},
        vips=vips or [],
        dashboard_base_url=dashboard_base_url,
        notifications_enabled=notifications_enabled,
    )
    return CompletionProcessor(
        contest_db=ContestDatabase.from_connection(conn),
        results=results,
        presence=presence,
        bonus_sender=sender,
        config=config,
    )
