"""Edge-path tests for CompletionProcessor, driven through ``run(conn)``.

Complements ``test_completion_processor.py`` (kept at its grandfathered size):
malformed or ambiguous payloads, already-announced milestones, and unparseable
dates. Each test names the behaviour, not the helper it happens to reach.
"""

import datetime
import logging

import pytest

from dk_results.notifications.vip_presence import VIP_PRESENT
from tests.completion_processor_fakes import (
    DummySport,
    FixedPresence,
    RecordingSender,
    StubResults,
    cashed_row,
    detail,
    insert_contest,
    leaderboard,
    make_conn,
    make_processor,
    record,
)


@pytest.fixture
def conn():
    connection = make_conn()
    yield connection
    connection.close()


def _run_soft_finish(conn, payload, *, vips=None):
    """Run a LIVE, unchanged contest whose leaderboard is ``payload``; return what was sent."""
    insert_contest(conn, status="LIVE")
    sender = RecordingSender()
    results = StubResults(detail=detail(status="LIVE"), leaderboard=payload)
    make_processor(conn, results=results, sender=sender, vips=vips).run(conn)
    return sender.messages


# ── Soft-finish: what counts as effectively final ───────────────────────────


def test_soft_finish_announces_a_well_formed_final_leaderboard():
    # The control for the malformed cases below: the same shape, all clean.
    conn = make_conn()
    messages = _run_soft_finish(conn, leaderboard())
    conn.close()
    assert len(messages) == 1
    assert "soft-finished" in messages[0]


@pytest.mark.parametrize(
    "payload",
    [
        leaderboard(leader="x"),
        leaderboard(last_winning="x"),
        leaderboard(rows=[]),
        leaderboard(rows="x"),
        leaderboard(rows=["x"]),
        leaderboard(leader={"timeRemaining": 5, "fantasyPoints": 229}),
        leaderboard(last_winning={"timeRemaining": 5, "fantasyPoints": 185.5}),
        leaderboard(rows=[cashed_row("FooBar", time_remaining=5)]),
        # Time remaining that is not a number never counts as finished.
        leaderboard(leader={"timeRemaining": None, "fantasyPoints": 229}),
        leaderboard(leader={"timeRemaining": True, "fantasyPoints": 229}),
        leaderboard(leader={"timeRemaining": "  ", "fantasyPoints": 229}),
        leaderboard(leader={"timeRemaining": "soon", "fantasyPoints": 229}),
    ],
    ids=[
        "leader-not-object",
        "last-winning-not-object",
        "no-rows",
        "rows-not-a-list",
        "row-not-object",
        "leader-still-playing",
        "last-winning-still-playing",
        "row-still-playing",
        "time-remaining-missing",
        "time-remaining-bool",
        "time-remaining-blank",
        "time-remaining-not-a-number",
    ],
)
def test_soft_finish_stays_silent_unless_every_part_is_finished(conn, payload):
    assert _run_soft_finish(conn, payload) == []


@pytest.mark.parametrize("missing", ["leader", "last_winning"])
def test_soft_finish_stays_silent_without_a_score_to_report(conn, missing):
    no_score = {"timeRemaining": 0, "fantasyPoints": "n/a"}
    assert _run_soft_finish(conn, leaderboard(**{missing: no_score})) == []


def test_soft_finish_lists_a_vip_once_when_the_leaderboard_repeats_the_name(conn):
    rows = [cashed_row("FooBar"), cashed_row("foobar")]
    messages = _run_soft_finish(conn, leaderboard(rows=rows), vips=["FooBar"])
    assert len(messages) == 1
    assert messages[0].lower().count("foobar") == 1


def test_soft_finish_is_skipped_when_the_live_contest_completes_mid_run(conn):
    insert_contest(conn, status="LIVE")
    sender = RecordingSender()
    # The sync pass sees LIVE (unchanged); by the soft-finish pass it has completed.
    results = StubResults(detail=[detail(status="LIVE"), detail(status="COMPLETED")], leaderboard=leaderboard())
    make_processor(conn, results=results, sender=sender, presence=None).run(conn)
    assert sender.messages == []


# ── Milestones that were already announced ───────────────────────────────────


def test_live_transition_already_announced_is_not_repeated(conn, caplog):
    insert_contest(conn)
    record(conn, 1, "live")
    sender = RecordingSender()
    processor = make_processor(conn, results=StubResults(detail=detail(status="LIVE")), sender=sender)
    with caplog.at_level(logging.INFO):
        processor.run(conn)
    assert sender.messages == []
    assert "live notification already sent" in caplog.text


def test_completed_transition_already_announced_is_not_repeated(conn, caplog):
    insert_contest(conn, status="LIVE")
    record(conn, 1, "live")
    record(conn, 1, "completed")
    sender = RecordingSender()
    processor = make_processor(conn, results=StubResults(detail=detail(status="COMPLETED")), sender=sender)
    with caplog.at_level(logging.INFO):
        processor.run(conn)
    assert sender.messages == []
    assert "completed notification already sent" in caplog.text


def test_completed_transition_without_a_live_announcement_is_skipped(conn, caplog):
    insert_contest(conn, status="LIVE")
    sender = RecordingSender()
    processor = make_processor(conn, results=StubResults(detail=detail(status="COMPLETED")), sender=sender)
    with caplog.at_level(logging.INFO):
        processor.run(conn)
    assert sender.messages == []
    assert "live notification missing" in caplog.text


# ── Warnings ─────────────────────────────────────────────────────────────────


def _upcoming_start(minutes: int) -> str:
    start = datetime.datetime.now() + datetime.timedelta(minutes=minutes)
    return start.strftime("%Y-%m-%d %H:%M:%S")


def test_warning_waits_until_the_contest_is_inside_its_window(conn):
    insert_contest(conn, start_date=_upcoming_start(120))
    sender = RecordingSender()
    processor = make_processor(
        conn,
        results=StubResults(detail=detail(status="LIVE")),
        sender=sender,
        presence=FixedPresence(VIP_PRESENT),
        warning_schedule=[25],
    )
    processor.run(conn)
    assert sender.messages == []


def test_warning_with_an_unparseable_start_date_is_skipped(conn):
    insert_contest(conn, start_date="not a date")
    sender = RecordingSender()
    processor = make_processor(
        conn,
        results=StubResults(detail=detail(status="UPCOMING")),
        sender=sender,
        presence=FixedPresence(VIP_PRESENT),
        warning_schedule=[25],
    )
    processor.run(conn)
    assert sender.messages == []


def test_warning_schedule_is_resolved_once_per_sport_name(conn, caplog):
    # Two sport keys that resolve to one sport name share one schedule lookup.
    insert_contest(conn, start_date=_upcoming_start(10))
    sender = RecordingSender()
    processor = make_processor(
        conn,
        results=StubResults(detail=detail(status="LIVE")),
        sender=sender,
        presence=FixedPresence(VIP_PRESENT),
        sport_choices={"NBA": DummySport, "NBA2": DummySport},
        warning_schedule=[25],
    )
    with caplog.at_level(logging.DEBUG):
        processor.run(conn)
    assert caplog.text.count("warning schedule for NBA") == 1
    assert len([m for m in sender.messages if m.startswith("Contest starting soon")]) == 1


# ── Contest detail edge cases ────────────────────────────────────────────────


def test_undecodable_contest_detail_is_logged_and_skipped(conn, caplog):
    insert_contest(conn)
    sender = RecordingSender()
    processor = make_processor(conn, results=StubResults(detail_error=ValueError("bad json")), sender=sender)
    with caplog.at_level(logging.ERROR):
        processor.run(conn)
    assert "JSON decoding error: bad json" in caplog.text
    assert sender.messages == []


def test_contest_detail_missing_fields_is_logged_and_skipped(conn, caplog):
    insert_contest(conn)
    sender = RecordingSender()
    processor = make_processor(conn, results=StubResults(detail={"contestDetail": {}}), sender=sender)
    with caplog.at_level(logging.ERROR):
        processor.run(conn)
    assert "Key error" in caplog.text
    assert sender.messages == []


def test_live_announcement_with_an_unparseable_start_date_omits_the_relative_time(conn):
    # Sorts before any real timestamp, so the DB still treats the contest as started.
    insert_contest(conn, start_date="1999-xx")
    sender = RecordingSender()
    processor = make_processor(
        conn,
        results=StubResults(detail=detail(status="LIVE")),
        sender=sender,
        presence=FixedPresence(VIP_PRESENT),
    )
    processor.run(conn)
    assert [m.split(":")[0] for m in sender.messages] == ["Contest started"]
