"""One-milestone scenarios for the CompletionProcessor tests (not collected by pytest).

Each ``run_*`` helper seeds one contest (``DK_ID``, ``NAME``), drives
``CompletionProcessor.run(conn)`` until that milestone fires, and returns the
``RecordingSender``. Extra keyword arguments go to ``make_processor``.
"""

from __future__ import annotations

import datetime

from tests.completion_processor_fakes import (
    RecordingSender,
    StubResults,
    detail,
    freeze_clock,
    insert_contest,
    leaderboard,
    make_processor,
    record,
)

DK_ID = 42
NAME = "Main Slate"
STARTED = "2024-01-01 00:00:00"
FAR_START = "2099-06-01 20:00:00"
FAR_NOW = datetime.datetime(2099, 6, 1, 19, 35)


def run_warning(conn, monkeypatch, *, now=FAR_NOW, start=FAR_START, schedule=(25,), **kwargs):
    """An upcoming contest whose warning window is open at the frozen ``now``."""
    freeze_clock(monkeypatch, now)
    insert_contest(conn, dk_id=DK_ID, name=NAME, start_date=start)
    sender = RecordingSender()
    results = StubResults(detail=detail(status="UPCOMING"))
    kwargs.setdefault("warning_schedule", list(schedule))
    make_processor(conn, results=results, sender=sender, **kwargs).run(conn)
    return sender


def run_live(conn, *, start=STARTED, **kwargs):
    """A started contest that DraftKings now reports LIVE."""
    insert_contest(conn, dk_id=DK_ID, name=NAME, start_date=start)
    sender = RecordingSender()
    unfinished = leaderboard(leader={"timeRemaining": 5, "fantasyPoints": 1})
    results = StubResults(detail=detail(status="LIVE"), leaderboard=unfinished)
    make_processor(conn, results=results, sender=sender, **kwargs).run(conn)
    return sender


def run_completed(conn, **kwargs):
    """A LIVE, already-announced contest that DraftKings now reports COMPLETED."""
    insert_contest(conn, dk_id=DK_ID, name=NAME, start_date=STARTED, status="LIVE")
    record(conn, DK_ID, "live")
    sender = RecordingSender()
    make_processor(conn, results=StubResults(detail=detail(status="COMPLETED")), sender=sender, **kwargs).run(conn)
    return sender


def run_soft_finish(conn, *, payload=None, start=STARTED, seed=True, sport="NBA", **kwargs):
    """An unchanged LIVE contest whose leaderboard is ``payload`` (default: a clean final one).

    ``seed=False`` re-runs against the contest an earlier call already inserted.
    """
    if seed:
        insert_contest(conn, dk_id=DK_ID, name=NAME, start_date=start, status="LIVE", sport=sport)
    sender = RecordingSender()
    results = StubResults(detail=detail(status="LIVE"), leaderboard=leaderboard() if payload is None else payload)
    make_processor(conn, results=results, sender=sender, **kwargs).run(conn)
    return sender
