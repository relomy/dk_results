"""CompletionProcessor starting-soon warnings: window, schedule and contest choice."""

import datetime
import logging

import pytest

from tests.completion_processor_fakes import (
    RecordingSender,
    StubResults,
    detail,
    freeze_clock,
    insert_contest,
    make_conn,
    make_processor,
    make_sport,
    record,
    stored_events,
)
from tests.completion_processor_scenarios import DK_ID, FAR_START, run_warning

START = datetime.datetime(2099, 6, 1, 20, 0, 0)


def _at(**delta):
    return START - datetime.timedelta(**delta)


@pytest.fixture
def conn():
    connection = make_conn()
    yield connection
    connection.close()


@pytest.mark.parametrize(
    ("now", "sent"),
    [
        (_at(minutes=25), True),
        (_at(minutes=24, seconds=59), True),
        (_at(seconds=1), True),
        (_at(minutes=25, seconds=1), False),
        (_at(), False),
        (_at(seconds=-1), False),
    ],
    ids=["exactly-at-window-edge", "inside", "one-second-out", "just-outside", "starting-now", "already-started"],
)
def test_warning_is_sent_only_while_the_start_is_inside_the_window(conn, monkeypatch, now, sent):
    assert bool(run_warning(conn, monkeypatch, now=now).messages) is sent


def test_warning_with_a_timezone_aware_start_is_measured_in_that_zone(conn, monkeypatch):
    start = "2099-06-01T20:00:00+00:00"
    now = datetime.datetime(2099, 6, 1, 19, 35, tzinfo=datetime.timezone.utc)
    sender = run_warning(conn, monkeypatch, now=now, start=start)
    assert sender.messages[0].splitlines()[1] == f"• 🕒 {start} (⏳ 25m)"


SCHEDULES = {
    "sport-key-is-lowercase": ({"nba": [60], "default": [10]}, None, ["warning:60"]),
    "sport-schedule-beats-default": ({"nba": [10], "default": [60]}, None, []),
    "empty-sport-schedule-uses-default": ({"nba": [], "default": [60]}, None, ["warning:60"]),
    "default-schedule": ({"default": [60]}, [25], ["warning:60"]),
    "configured-default-without-a-default-key": ({}, [60], ["warning:60"]),
    "several-entries": ({"default": [60, 10, 45]}, None, ["warning:60", "warning:45"]),
}


@pytest.mark.parametrize(("schedules", "fallback", "kinds"), SCHEDULES.values(), ids=SCHEDULES.keys())
def test_warning_schedule_is_looked_up_by_lowercase_sport_name(conn, monkeypatch, schedules, fallback, kinds):
    run_warning(conn, monkeypatch, now=_at(minutes=40), warning_schedules=schedules, default_warning_schedule=fallback)
    assert stored_events(conn, DK_ID) == kinds


def test_warning_already_announced_is_not_repeated(conn, monkeypatch, caplog):
    insert_contest(conn, dk_id=DK_ID, name="Main", start_date=FAR_START)
    record(conn, DK_ID, "warning:25")
    freeze_clock(monkeypatch, _at(minutes=20))
    sender = RecordingSender()
    processor = make_processor(conn, results=StubResults(), sender=sender, warning_schedule=[25])
    with caplog.at_level(logging.DEBUG):
        processor.run(conn)
    assert sender.messages == []
    assert "warning already sent for NBA dk_id=42 (25m)" in caplog.messages


@pytest.mark.parametrize(
    ("schedules", "source"),
    [({"nba": [25]}, "sport"), ({"default": [25]}, "default")],
)
def test_warning_schedule_resolution_is_logged_with_its_source(conn, monkeypatch, caplog, schedules, source):
    with caplog.at_level(logging.DEBUG):
        run_warning(conn, monkeypatch, warning_schedules=schedules)
    assert f"warning schedule for NBA: [25] (source={source})" in caplog.messages


def _seed_contests(conn):
    rows = [
        (1, "Main Event", 100, "2099-06-01 20:00:00"),
        (2, "Satellite", 30, "2099-06-01 19:40:00"),
        (3, "Main small", 30, "2099-06-01 19:50:00"),
        (4, "Big Other", 100, "2099-06-01 19:45:00"),
    ]
    for dk_id, name, fee, start in rows:
        insert_contest(conn, dk_id=dk_id, name=name, entry_fee=fee, start_date=start)


def _warn_with_sport(conn, monkeypatch, sport):
    freeze_clock(monkeypatch, datetime.datetime(2099, 6, 1, 19, 30))
    sender = RecordingSender()
    results = StubResults(detail=detail(status="UPCOMING"))
    make_processor(conn, results=results, sender=sender, sport_choices={"NBA": sport}, warning_schedule=[60]).run(conn)
    return sender.messages


def test_warning_targets_the_next_contest_matching_the_sports_fee_and_keyword(conn, monkeypatch):
    _seed_contests(conn)
    messages = _warn_with_sport(conn, monkeypatch, make_sport("NBA", fee=50, keyword="%Main%"))
    assert [m.splitlines()[0] for m in messages] == ["Contest starting soon (60m): 🏀 NBA — Main Event"]
    assert stored_events(conn, 1) == ["warning:60"]


def test_warning_falls_back_to_the_next_contest_when_none_matches(conn, monkeypatch):
    _seed_contests(conn)
    messages = _warn_with_sport(conn, monkeypatch, make_sport("NBA", fee=500, keyword="%Main%"))
    assert [m.splitlines()[0] for m in messages] == ["Contest starting soon (60m): 🏀 NBA — Satellite"]
