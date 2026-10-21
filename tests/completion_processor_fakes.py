"""Fakes and builders for the CompletionProcessor characterization tests.

Not a ``test_`` module, so pytest does not collect it. The edge tests that use it
drive ``CompletionProcessor.run(conn)`` with a real in-memory ``ContestDatabase``
and ``NotificationStore`` and fakes only at the DraftKings and Discord edges.
"""

from __future__ import annotations

import sqlite3

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


class RecordingSender:
    """A BonusSenderPort that records everything sent."""

    def __init__(self) -> None:
        self.messages: list[str] = []

    def send_message(self, message: str) -> None:
        self.messages.append(message)


class FixedPresence:
    """A presence oracle returning one canned verdict."""

    def __init__(self, verdict: str) -> None:
        self._verdict = verdict

    def verdict(self, dk_id: int, start_date: str, vip_names: list[str]) -> str:
        return self._verdict


class StubResults:
    """A ContestResultsPort serving detail payloads (or raising) and one leaderboard.

    ``detail`` may be a list: each call consumes one entry and the last repeats.
    """

    def __init__(self, *, detail=None, leaderboard=None, detail_error: Exception | None = None) -> None:
        self._detail = list(detail) if isinstance(detail, list) else detail
        self._leaderboard = leaderboard
        self._detail_error = detail_error

    def get_contest_detail(self, dk_id, timeout=None):
        if self._detail_error is not None:
            raise self._detail_error
        if isinstance(self._detail, list):
            return self._detail.pop(0) if len(self._detail) > 1 else self._detail[0]
        return self._detail

    def get_leaderboard(self, contest_id, timeout=None, session=None):
        return self._leaderboard

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


def cashed_row(user: str, *, time_remaining=0) -> dict:
    return {"userName": user, "timeRemaining": time_remaining, "fantasyPoints": 229, "winningValue": 100.0}


def make_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute(CONTESTS_TABLE_SQL)
    conn.commit()
    return conn


def insert_contest(conn, *, dk_id=1, name="Contest1", start_date="2024-01-01 00:00:00", status="UPCOMING", completed=0):
    conn.execute(
        """
        INSERT INTO contests (
            dk_id, sport, name, start_date, draft_group, total_prizes, entries,
            positions_paid, entry_fee, entry_count, max_entry_count, completed, status
        ) VALUES (?, 'NBA', ?, ?, 1, 0, 100, NULL, 25, 0, 1, ?, ?)
        """,
        (dk_id, name, start_date, completed, status),
    )
    conn.commit()


def record(conn, dk_id: int, kind: str) -> None:
    NotificationStore(conn).record_notification(dk_id, kind)


def make_processor(conn, *, results, sender, presence=None, vips=None, sport_choices=None, warning_schedule=None):
    config = CompletionProcessorConfig(
        sport_choices=sport_choices if sport_choices is not None else {"NBA": DummySport},
        warning_schedules={"default": warning_schedule or []},
        default_warning_schedule=[25],
        sport_emoji={"NBA": "🏀"},
        spreadsheet_id=None,
        sheet_gid_map={},
        vips=vips or [],
        dashboard_base_url=None,
    )
    return CompletionProcessor(
        contest_db=ContestDatabase.from_connection(conn),
        results=results,
        presence=presence,
        bonus_sender=sender,
        config=config,
    )
