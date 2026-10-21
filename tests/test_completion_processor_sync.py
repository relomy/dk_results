"""CompletionProcessor state sync and the live/completed transitions it announces."""

import logging

import pytest

from tests.completion_processor_fakes import (
    RecordingSender,
    StubResults,
    contest_row,
    detail,
    insert_contest,
    leaderboard,
    make_conn,
    make_processor,
    make_sport,
    record,
    stored_events,
)


@pytest.fixture
def conn():
    connection = make_conn()
    yield connection
    connection.close()


def _run(conn, status="LIVE", *, sender=None, results=None, **kwargs):
    sender = sender or RecordingSender()
    results = results or StubResults(detail=detail(status=status), leaderboard=leaderboard(leader={"timeRemaining": 3}))
    make_processor(conn, results=results, sender=sender, **kwargs).run(conn)
    return sender.messages


SYNCED = {
    "positions-paid-only": ((None, "LIVE", 0), "LIVE", (10, "LIVE", 0)),
    "status-only": ((10, "UPCOMING", 0), "LIVE", (10, "LIVE", 0)),
    "completed-only": ((10, "COMPLETED", 0), "COMPLETED", (10, "COMPLETED", 1)),
}


@pytest.mark.parametrize(("stored", "reported", "expected"), SYNCED.values(), ids=SYNCED.keys())
def test_any_single_changed_field_updates_the_stored_contest(conn, stored, reported, expected):
    positions_paid, status, completed = stored
    insert_contest(conn, status=status, completed=completed, positions_paid=positions_paid)
    _run(conn, reported)
    assert contest_row(conn) == expected


def test_contests_in_an_already_synced_draft_group_are_not_fetched_again(conn):
    for dk_id, group, entries, status in [(1, 1, 100, "LIVE"), (2, 1, 100, "LIVE"), (3, 2, 500, "UPCOMING")]:
        insert_contest(conn, dk_id=dk_id, draft_group=group, entries=entries, status=status, positions_paid=10)
    results = StubResults(detail=detail(status="LIVE"), leaderboard=leaderboard(leader={"timeRemaining": 3}))
    messages = _run(conn, results=results)
    assert results.detail_calls[:2] == [1, 3]
    assert [m.splitlines()[0] for m in messages] == ["Contest started: 🏀 NBA — Contest1"]
    assert stored_events(conn, 3) == ["live"]


def test_skipped_contests_are_logged_with_their_name_and_draft_group(conn, caplog):
    insert_contest(conn, dk_id=1, status="LIVE", positions_paid=10)
    insert_contest(conn, dk_id=2, name="Contest2", status="LIVE", positions_paid=10)
    with caplog.at_level(logging.DEBUG):
        _run(conn)
    assert "dk_id: 2 positions_paid: 10" in caplog.messages
    assert "skipping Contest2 because we've already updated 1 [skipped draft groups 1]" in caplog.messages


def test_contest_fetch_is_logged_with_its_stored_state(conn, caplog):
    insert_contest(conn)
    with caplog.at_level(logging.DEBUG):
        _run(conn)
    assert "getting contest data for Contest1 [id: 1 start: 2024-01-01 00:00:00 dg: 1]" in caplog.messages
    assert "existing: status: UPCOMING entries: 100 positions_paid: None" in caplog.messages


COMPLETIONS = {
    "live-to-completed": ("LIVE", 0, 10, "COMPLETED", True),
    "live-to-cancelled": ("LIVE", 0, 10, "CANCELLED", True),
    "flag-not-set-yet": ("LIVE", 1, None, "COMPLETED", True),
    "status-already-completed-flag-not-set": ("COMPLETED", 0, 10, "COMPLETED", True),
    "already-completed-and-flagged": ("COMPLETED", 1, None, "COMPLETED", False),
    "still-live": ("LIVE", 0, 10, "LIVE", False),
}


@pytest.mark.parametrize(
    ("status", "completed", "positions_paid", "reported", "announced"), COMPLETIONS.values(), ids=COMPLETIONS.keys()
)
def test_completed_is_announced_when_status_or_flag_newly_turns_completed(
    conn, status, completed, positions_paid, reported, announced
):
    insert_contest(conn, status=status, completed=completed, positions_paid=positions_paid)
    record(conn, 1, "live")
    messages = _run(conn, reported)
    assert [m.split(":")[0] for m in messages] == (["Contest ended"] if announced else [])
    assert stored_events(conn) == (["live", "completed"] if announced else ["live"])


def test_completed_notification_already_sent_is_logged_with_the_contest(conn, caplog):
    insert_contest(conn, status="LIVE")
    record(conn, 1, "live")
    record(conn, 1, "completed")
    with caplog.at_level(logging.INFO):
        _run(conn, "COMPLETED")
    assert "completed notification already sent for NBA dk_id=1" in caplog.messages


def test_live_is_announced_only_for_the_sports_primary_live_contest(conn):
    insert_contest(conn, dk_id=1, draft_group=1, entry_fee=100, status="LIVE", positions_paid=10)
    insert_contest(conn, dk_id=2, draft_group=2, entry_fee=25, status="UPCOMING")
    assert _run(conn) == []
    assert stored_events(conn, 2) == []


def test_primary_live_contest_follows_the_sports_entry_fee_and_keyword(conn):
    insert_contest(conn, dk_id=1, draft_group=1, name="Main A", entry_fee=50, entries=10, status="UPCOMING")
    insert_contest(conn, dk_id=2, draft_group=2, name="Other", entry_fee=100, status="LIVE", positions_paid=10)
    messages = _run(conn, sport_choices={"NBA": make_sport("NBA", fee=50, keyword="%Main%")})
    assert [m.splitlines()[0] for m in messages] == ["Contest started: 🏀 NBA — Main A"]


def test_soft_finish_targets_the_live_contest_matching_the_sports_fee_and_keyword(conn):
    insert_contest(conn, dk_id=1, draft_group=1, name="Main A", entry_fee=50, status="LIVE", positions_paid=10)
    insert_contest(conn, dk_id=2, draft_group=2, name="Other", entry_fee=100, status="LIVE", positions_paid=10)
    results = StubResults(detail=detail(status="LIVE"), leaderboard=leaderboard())
    messages = _run(conn, results=results, sport_choices={"NBA": make_sport("NBA", fee=50, keyword="%Main%")})
    assert [m.splitlines()[0] for m in messages] == ["Contest soft-finished: 🏀 NBA — Main A"]


def test_disabled_notifications_still_sync_the_contest_but_announce_nothing(conn):
    insert_contest(conn)
    assert _run(conn, notifications_enabled=False) == []
    assert contest_row(conn) == (10, "LIVE", 0)
    assert stored_events(conn) == []


def test_contest_of_an_untracked_sport_is_synced_quietly(conn, caplog):
    insert_contest(conn, sport="MLB")
    with caplog.at_level(logging.ERROR):
        assert _run(conn) == []
    assert contest_row(conn) == (10, "LIVE", 0)
    assert caplog.text == ""


def test_completed_without_a_live_announcement_is_skipped_and_logged(conn, caplog):
    insert_contest(conn, status="LIVE")
    with caplog.at_level(logging.INFO):
        assert _run(conn, "COMPLETED") == []
    assert "skipping completed notification for NBA dk_id=1; live notification missing" in caplog.messages
