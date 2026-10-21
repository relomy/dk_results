"""CompletionProcessor keeps going to the next sport after one sport is skipped.

Each case puts a skippable sport first and a healthy one second, then expects
exactly the healthy sport's announcement.
"""

import logging

import pytest

from dk_results.notifications.vip_presence import VIP_ABSENT, VIP_PRESENT
from tests.completion_processor_fakes import (
    FixedPresence,
    RecordingSender,
    StubResults,
    detail,
    freeze_clock,
    insert_contest,
    leaderboard,
    make_conn,
    make_processor,
    make_sport,
)
from tests.completion_processor_scenarios import FAR_NOW, FAR_START

SPORTS = {"NBA": make_sport("NBA"), "MLB": make_sport("MLB")}


@pytest.fixture
def conn():
    connection = make_conn()
    yield connection
    connection.close()


def _soft_finish_pair(conn, *, first=True, presence=None, **result_kwargs):
    """A LIVE contest per sport (NBA first); returns what was sent."""
    if first:
        insert_contest(conn, dk_id=1, sport="NBA", name="First", status="LIVE")
    insert_contest(conn, dk_id=2, sport="MLB", name="Second", status="LIVE")
    sender = RecordingSender()
    results = StubResults(detail=detail(status="LIVE"), leaderboard=leaderboard(), **result_kwargs)
    make_processor(conn, results=results, sender=sender, presence=presence, sport_choices=SPORTS).run(conn)
    return sender.messages


SOFT_FINISH_SKIPS = {
    "no-live-contest": {"first": False},
    "detail-unavailable": {"details_by_id": {1: ValueError("boom")}},
    "completed-mid-run": {"details_by_id": {1: [detail(status="LIVE"), detail(status="COMPLETED")]}},
    "vip-absent": {"presence": FixedPresence(VIP_PRESENT, by_id={1: VIP_ABSENT})},
    "leaderboard-fails": {"leaderboards_by_id": {1: RuntimeError("down")}},
}


@pytest.mark.parametrize("skip", SOFT_FINISH_SKIPS.values(), ids=SOFT_FINISH_SKIPS.keys())
def test_soft_finish_moves_on_to_the_next_sport(conn, skip):
    messages = _soft_finish_pair(conn, **skip)
    assert len(messages) == 1
    assert messages[0].startswith("Contest soft-finished: ")
    assert "MLB — Second" in messages[0]


def test_soft_finish_logs_a_vip_absent_skip(conn, caplog):
    with caplog.at_level(logging.INFO):
        _soft_finish_pair(conn, presence=FixedPresence(VIP_PRESENT, by_id={1: VIP_ABSENT}))
    assert "skipping soft-finish notification for NBA dk_id=1; vip_presence=absent" in caplog.messages


def test_soft_finish_logs_a_failed_evaluation(conn, caplog):
    with caplog.at_level(logging.WARNING):
        _soft_finish_pair(conn, leaderboards_by_id={1: RuntimeError("down")})
    [failure] = [r for r in caplog.records if r.getMessage() == "soft-finish evaluation failed for NBA dk_id=1"]
    assert failure.exc_info is not None


def _warning_pair(conn, monkeypatch, *, nba_start=None):
    """NBA's next contest is ``nba_start`` (or absent); MLB's opens its window now."""
    freeze_clock(monkeypatch, FAR_NOW)
    if nba_start:
        insert_contest(conn, dk_id=1, sport="NBA", name="First", start_date=nba_start)
    insert_contest(conn, dk_id=2, sport="MLB", name="Second", start_date=FAR_START)
    sender = RecordingSender()
    results = StubResults(detail=detail(status="UPCOMING"))
    make_processor(conn, results=results, sender=sender, sport_choices=SPORTS, warning_schedule=[25]).run(conn)
    return sender.messages


@pytest.mark.parametrize("nba_start", [None, "not a date"], ids=["no-upcoming-contest", "unparseable-start-date"])
def test_warnings_move_on_to_the_next_sport(conn, monkeypatch, nba_start):
    messages = _warning_pair(conn, monkeypatch, nba_start=nba_start)
    assert len(messages) == 1
    assert messages[0].startswith("Contest starting soon (25m): ")
    assert "MLB — Second" in messages[0]
