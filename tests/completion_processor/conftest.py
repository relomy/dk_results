"""Fixtures for the CompletionProcessor tests.

The tests drive ``CompletionProcessor.run(conn)`` against a real in-memory
``ContestDatabase`` and ``NotificationStore``, with fakes only at the DraftKings
and Discord edges and a fixed clock injected as ``now=``. The ``run_*`` fixtures
seed one contest, run the processor until one milestone fires and return the
``sender`` that recorded what was sent.
"""

from __future__ import annotations

import datetime
import sqlite3
from dataclasses import dataclass

import pytest

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

# The clock when a test does not pick one: long after every started contest below.
DEFAULT_MOMENT = datetime.datetime(2030, 1, 1, 12, 0, tzinfo=datetime.timezone.utc)


class DummySport:
    name = "NBA"
    sheet_min_entry_fee = 25
    keyword = "%"


class RecordingSender:
    """A BonusSenderPort that records everything sent, or raises ``fail_with`` instead."""

    def __init__(self, fail_with: Exception | None = None) -> None:
        self.messages: list[str] = []
        self._fail_with = fail_with

    def send_message(self, message: str) -> None:
        if self._fail_with is not None:
            raise self._fail_with
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


def _next_of(source):
    """A list is consumed one entry per call and its last entry repeats; an exception is raised."""
    if isinstance(source, list):
        source = source.pop(0) if len(source) > 1 else source[0]
    if isinstance(source, Exception):
        raise source
    return source


def _copied(source):
    return list(source) if isinstance(source, list) else source


class StubResults:
    """A ContestResultsPort serving detail payloads (or raising) and one leaderboard.

    ``detail`` and ``leaderboard`` may be a list: each call consumes one entry and the
    last repeats. An exception in place of a payload is raised. ``details_by_id`` /
    ``leaderboards_by_id`` override those per contest; ``detail_calls`` records every
    contest id whose detail was fetched.
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
        self._detail = _copied(detail)
        self._leaderboard = _copied(leaderboard)
        self._detail_error = detail_error
        self._details_by_id = {k: _copied(v) for k, v in (details_by_id or {}).items()}
        self._leaderboards_by_id = {k: _copied(v) for k, v in (leaderboards_by_id or {}).items()}
        self.detail_calls: list[int] = []

    def get_contest_detail(self, dk_id, timeout=None):
        self.detail_calls.append(dk_id)
        if self._detail_error is not None:
            raise self._detail_error
        return _next_of(self._details_by_id.get(dk_id, self._detail))

    def get_leaderboard(self, contest_id, timeout=None, session=None):
        return _next_of(self._leaderboards_by_id.get(contest_id, self._leaderboard))

    def get_contest_entrants_page(self, contest_id, page_no, timeout=None, session=None):
        return ""


@dataclass(frozen=True)
class Scenario:
    """The one contest the ``run_*`` fixtures seed, and the times around it."""

    dk_id: int = 42
    name: str = "Main Slate"
    started: str = "2024-01-01 00:00:00"
    far_start: str = "2099-06-01 20:00:00"  # after the DB's own "now", so it counts as upcoming
    far_now: datetime.datetime = datetime.datetime(2099, 6, 1, 19, 35)  # 25 minutes before far_start


# ── Edges, clock and store ───────────────────────────────────────────────────


@pytest.fixture
def conn():
    connection = sqlite3.connect(":memory:")
    connection.execute(CONTESTS_TABLE_SQL)
    connection.commit()
    yield connection
    connection.close()


@pytest.fixture
def clock_at():
    """``clock_at(moment)``: a ``now(tz)`` callable fixed at ``moment``.

    Like ``datetime.datetime.now``: a naive call returns ``moment`` as a naive wall time,
    an aware call converts it (``moment`` must then be aware).
    """

    def build(moment: datetime.datetime):
        def now(tz=None):
            return moment.replace(tzinfo=None) if tz is None else moment.astimezone(tz)

        return now

    return build


@pytest.fixture
def sender():
    return RecordingSender()


@pytest.fixture
def failing_sender():
    return RecordingSender(fail_with=RuntimeError("send failed"))


@pytest.fixture
def make_presence():
    return FixedPresence


@pytest.fixture
def make_results():
    return StubResults


@pytest.fixture
def make_sport():
    def build(name: str, *, fee: int = 25, keyword: str = "%") -> type:
        """A sport class with its own name, minimum entry fee and contest-name keyword."""
        return type(f"{name}Sport", (), {"name": name, "sheet_min_entry_fee": fee, "keyword": keyword})

    return build


@pytest.fixture
def scenario():
    return Scenario()


@pytest.fixture
def bare_text():
    def build(prefix: str, *, name: str = "Contest1", dk_id: int = 1, when: str = "2024-01-01 00:00:00") -> str:
        """A warning / live / completed message when no sheet or dashboard is configured."""
        link = f"https://www.draftkings.com/contest/gamecenter/{dk_id}#/"
        return "\n".join(
            [f"{prefix}: 🏀 NBA — {name}", f"• 🕒 {when}", f"• 🔗 DK: [{dk_id}](<{link}>)", "• 📊 Sheet: n/a"]
        )

    return build


# ── Payloads ─────────────────────────────────────────────────────────────────


@pytest.fixture
def detail():
    def build(*, status: str, positions_paid: int = 10) -> dict:
        return {
            "contestDetail": {
                "payoutSummary": [{"maxPosition": positions_paid}],
                "contestStateDetail": status,
                "maximumEntries": 100,
            }
        }

    return build


@pytest.fixture
def cashed_row():
    def build(user, *, time_remaining=0, winning_value=100.0) -> dict:
        return {"userName": user, "timeRemaining": time_remaining, "fantasyPoints": 229, "winningValue": winning_value}

    return build


@pytest.fixture
def leaderboard(cashed_row):
    def build(*, leader=None, last_winning=None, rows=None) -> dict:
        """A leaderboard payload; each part defaults to a finished (zero time remaining) one."""
        return {
            "leader": {"timeRemaining": 0, "fantasyPoints": 229} if leader is None else leader,
            "lastWinningEntry": {"timeRemaining": 0, "fantasyPoints": 185.5} if last_winning is None else last_winning,
            "leaderBoard": [cashed_row("FooBar")] if rows is None else rows,
        }

    return build


# ── The contest store ────────────────────────────────────────────────────────


@pytest.fixture
def insert_contest(conn):
    def insert(
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

    return insert


@pytest.fixture
def contest_row(conn):
    def read(dk_id: int = 1) -> tuple:
        """The contest's synced ``(positions_paid, status, completed)``."""
        sql = "SELECT positions_paid, status, completed FROM contests WHERE dk_id=?"
        return conn.execute(sql, (dk_id,)).fetchone()

    return read


@pytest.fixture
def record(conn):
    def store(dk_id: int, kind: str) -> None:
        NotificationStore(conn).record_notification(dk_id, kind)

    return store


@pytest.fixture
def stored_events(conn):
    def read(dk_id: int = 1) -> list[str]:
        """The notification events recorded for a contest, oldest first."""
        rows = conn.execute("SELECT event FROM contest_notifications WHERE dk_id=? ORDER BY rowid", (dk_id,))
        return [event for (event,) in rows]

    return read


# ── The processor under test ─────────────────────────────────────────────────


@pytest.fixture
def make_processor(conn, clock_at):
    def build(
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
        now=None,
        clock=None,
    ):
        config = CompletionProcessorConfig(
            sport_choices=sport_choices if sport_choices is not None else {"NBA": DummySport},
            warning_schedules=warning_schedules
            if warning_schedules is not None
            else {"default": warning_schedule or []},
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
            clock=clock,
            now=now or clock_at(DEFAULT_MOMENT),
        )

    return build


@pytest.fixture
def run_sync(conn, sender, detail, leaderboard, make_results, make_processor):
    def run(status="LIVE", *, results=None, **kwargs):
        """One run over whatever contests are seeded, DraftKings reporting ``status``; returns what was sent."""
        unfinished = leaderboard(leader={"timeRemaining": 3})
        results = results or make_results(detail=detail(status=status), leaderboard=unfinished)
        make_processor(results=results, sender=sender, **kwargs).run(conn)
        return sender.messages

    return run


# ── One-milestone scenarios ──────────────────────────────────────────────────


@pytest.fixture
def run_warning(conn, scenario, clock_at, insert_contest, detail, make_results, make_processor):
    def run(*, at=None, start=None, schedule=(25,), **kwargs):
        """An upcoming contest whose warning window is open at ``at`` (default: 25 minutes before)."""
        insert_contest(dk_id=scenario.dk_id, name=scenario.name, start_date=start or scenario.far_start)
        kwargs.setdefault("warning_schedule", list(schedule))
        sender, results = RecordingSender(), make_results(detail=detail(status="UPCOMING"))
        make_processor(results=results, sender=sender, now=clock_at(at or scenario.far_now), **kwargs).run(conn)
        return sender

    return run


@pytest.fixture
def run_live(conn, scenario, clock_at, insert_contest, detail, leaderboard, make_results, make_processor):
    def run(*, start=None, at=None, **kwargs):
        """A started contest that DraftKings now reports LIVE."""
        insert_contest(dk_id=scenario.dk_id, name=scenario.name, start_date=start or scenario.started)
        unfinished = leaderboard(leader={"timeRemaining": 5, "fantasyPoints": 1})
        sender, results = RecordingSender(), make_results(detail=detail(status="LIVE"), leaderboard=unfinished)
        make_processor(results=results, sender=sender, now=at and clock_at(at), **kwargs).run(conn)
        return sender

    return run


@pytest.fixture
def run_completed(conn, scenario, insert_contest, record, detail, make_results, make_processor):
    def run(**kwargs):
        """A LIVE, already-announced contest that DraftKings now reports COMPLETED."""
        insert_contest(dk_id=scenario.dk_id, name=scenario.name, start_date=scenario.started, status="LIVE")
        record(scenario.dk_id, "live")
        sender, results = RecordingSender(), make_results(detail=detail(status="COMPLETED"))
        make_processor(results=results, sender=sender, **kwargs).run(conn)
        return sender

    return run


@pytest.fixture
def run_soft_finish(conn, scenario, clock_at, insert_contest, detail, leaderboard, make_results, make_processor):
    def run(*, payload=None, start=None, seed=True, sport="NBA", at=None, **kwargs):
        """An unchanged LIVE contest whose leaderboard is ``payload`` (default: a clean final one).

        ``seed=False`` re-runs against the contest an earlier call already inserted.
        """
        if seed:
            insert_contest(
                dk_id=scenario.dk_id,
                name=scenario.name,
                start_date=start or scenario.started,
                status="LIVE",
                sport=sport,
            )
        sender = RecordingSender()
        results = make_results(detail=detail(status="LIVE"), leaderboard=leaderboard() if payload is None else payload)
        make_processor(results=results, sender=sender, now=at and clock_at(at), **kwargs).run(conn)
        return sender

    return run
