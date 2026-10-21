"""CompletionProcessor state sync: what is written back from DraftKings, and what is skipped."""

import datetime
import logging

import pytest

from dk_results.completion_processor.sync import fetch_contest_state
from dk_results.persistence.contestdatabase import ContestDatabase

SYNCED = {
    "positions-paid-only": ((None, "LIVE", 0), "LIVE", (10, "LIVE", 0)),
    "status-only": ((10, "UPCOMING", 0), "LIVE", (10, "LIVE", 0)),
    "completed-only": ((10, "COMPLETED", 0), "COMPLETED", (10, "COMPLETED", 1)),
}


@pytest.mark.parametrize(("stored", "reported", "expected"), SYNCED.values(), ids=SYNCED.keys())
def test_any_single_changed_field_updates_the_stored_contest(
    insert_contest, run_sync, contest_row, stored, reported, expected
):
    positions_paid, status, completed = stored
    insert_contest(status=status, completed=completed, positions_paid=positions_paid)
    run_sync(reported)
    assert contest_row() == expected


def test_contests_in_an_already_synced_draft_group_are_not_fetched_again(
    insert_contest, run_sync, detail, leaderboard, make_results, stored_events
):
    for dk_id, group, entries, status in [(1, 1, 100, "LIVE"), (2, 1, 100, "LIVE"), (3, 2, 500, "UPCOMING")]:
        insert_contest(dk_id=dk_id, draft_group=group, entries=entries, status=status, positions_paid=10)
    results = make_results(detail=detail(status="LIVE"), leaderboard=leaderboard(leader={"timeRemaining": 3}))
    messages = run_sync(results=results)
    assert results.detail_calls[:2] == [1, 3]
    assert [m.splitlines()[0] for m in messages] == ["Contest started: 🏀 NBA — Contest1"]
    assert stored_events(3) == ["live"]


def test_same_draft_group_skips_following_contest_after_unchanged_update(
    conn, insert_contest, detail, make_results, make_processor
):
    for dk_id, name in [(1, "First"), (2, "Second")]:
        insert_contest(dk_id=dk_id, name=name, status="LIVE", draft_group=7, positions_paid=10)
    results = make_results(detail=detail(status="LIVE"))

    make_processor(results=results, sender=None).run(conn)

    assert results.detail_calls == [1]


def test_skipped_contests_are_logged_with_their_name_and_draft_group(insert_contest, run_sync, caplog):
    insert_contest(dk_id=1, status="LIVE", positions_paid=10)
    insert_contest(dk_id=2, name="Contest2", status="LIVE", positions_paid=10)
    with caplog.at_level(logging.DEBUG):
        run_sync()
    assert "dk_id: 2 positions_paid: 10" in caplog.messages
    assert "skipping Contest2 because we've already updated 1 [skipped draft groups 1]" in caplog.messages


def test_contest_fetch_is_logged_with_its_stored_state(insert_contest, run_sync, caplog):
    insert_contest()
    with caplog.at_level(logging.DEBUG):
        run_sync()
    assert "getting contest data for Contest1 [id: 1 start: 2024-01-01 00:00:00 dg: 1]" in caplog.messages
    assert "existing: status: UPCOMING entries: 100 positions_paid: None" in caplog.messages


def test_contest_sync_logs_a_compact_fetch_line_not_the_raw_payload(
    insert_contest, run_sync, detail, make_results, caplog
):
    insert_contest()
    results = make_results(detail=detail(status="COMPLETED", positions_paid=42))

    with caplog.at_level(logging.DEBUG):
        run_sync(results=results)

    assert not [r for r in caplog.records if isinstance(r.msg, dict)]
    fetched = [m for m in caplog.messages if m.startswith("contest_fetched ")]
    assert fetched == ["contest_fetched dk_id=1 status=COMPLETED completed=1 positions_paid=42"]


def test_state_sync_updates_db_without_sender(conn, insert_contest, detail, make_results, make_processor):
    insert_contest()
    results = make_results(detail=detail(status="COMPLETED", positions_paid=42))

    make_processor(results=results, sender=None).run(conn)

    db = ContestDatabase.from_connection(conn)
    assert db.get_contest_state(1) == ("COMPLETED", 1)
    row = db.get_contest_by_id(1)
    assert row is not None and row.positions_paid == 42


def test_disabled_notifications_still_sync_the_contest_but_announce_nothing(
    insert_contest, run_sync, contest_row, stored_events
):
    insert_contest()
    assert run_sync(notifications_enabled=False) == []
    assert contest_row() == (10, "LIVE", 0)
    assert stored_events() == []


def test_disabled_notifications_send_nothing_even_with_sender(insert_contest, run_sync, make_presence, contest_row):
    """A disabled run still advances state but short-circuits every send.

    Story 7: ``notifications_enabled`` is the authority, independent of whether a
    sender is wired. Here a live transition would normally announce, but the
    disabled flag suppresses it while the DB is still advanced to LIVE.
    """
    insert_contest()

    sent = run_sync(presence=make_presence("unknown"), notifications_enabled=False)

    assert sent == []
    # State sync is not gated: the contest advanced to LIVE.
    assert contest_row() == (10, "LIVE", 0)


def test_contest_of_an_untracked_sport_is_synced_quietly(insert_contest, run_sync, contest_row, caplog):
    insert_contest(sport="MLB")
    with caplog.at_level(logging.ERROR):
        assert run_sync() == []
    assert contest_row() == (10, "LIVE", 0)
    assert caplog.text == ""


def test_completed_contest_is_stamped_with_the_processor_clock_and_never_moved(
    conn, insert_contest, detail, make_results, make_processor
):
    insert_contest(status="LIVE")
    fixed = datetime.datetime(2026, 10, 10, 12, 0, tzinfo=datetime.timezone.utc)
    results = make_results(detail=detail(status="COMPLETED", positions_paid=42))
    make_processor(results=results, sender=None, clock=lambda: fixed).run(conn)

    # A later run observes the same COMPLETED status; the stamp must not move.
    later = fixed + datetime.timedelta(hours=10)
    results = make_results(detail=detail(status="COMPLETED", positions_paid=43))
    make_processor(results=results, sender=None, clock=lambda: later).run(conn)

    db = ContestDatabase.from_connection(conn)
    assert db.get_recently_completed_contest("NBA", now=fixed + datetime.timedelta(hours=1)) is not None
    assert db.get_recently_completed_contest("NBA", now=fixed + datetime.timedelta(hours=19)) is None


def test_cancelled_contest_is_not_stamped_by_the_processor(
    conn, insert_contest, detail, make_results, make_processor, clock_at
):
    insert_contest(status="LIVE")
    moment = datetime.datetime(2026, 10, 10, 12, 0, tzinfo=datetime.timezone.utc)
    results = make_results(detail=detail(status="CANCELLED"))
    make_processor(results=results, sender=None, now=clock_at(moment)).run(conn)

    db = ContestDatabase.from_connection(conn)
    assert db.get_contest_state(1) == ("CANCELLED", 1)
    assert db.get_recently_completed_contest("NBA", now=moment) is None


def test_unavailable_results_are_skipped_gracefully(conn, sender, insert_contest, make_results, make_processor):
    insert_contest()
    unavailable = RuntimeError("unavailable")
    results = make_results(detail_error=unavailable, leaderboard=unavailable)

    make_processor(results=results, sender=sender, presence=None).run(conn)  # must not raise

    # Nothing updated because the read failed.
    assert ContestDatabase.from_connection(conn).get_contest_state(1) == ("UPCOMING", 0)


def test_fetched_contest_state_is_normalised_and_unfinished_statuses_are_dropped(make_results, detail):
    assert fetch_contest_state(make_results(detail=detail(status="live", positions_paid=5)), 1) == {
        "completed": 0,
        "status": "LIVE",
        "entries": 100,
        "positions_paid": 5,
    }
    assert fetch_contest_state(make_results(detail=detail(status="POSTPONED")), 2) is None


def test_completed_statuses_constant():
    from dk_results.completion_processor import COMPLETED_STATUSES

    assert COMPLETED_STATUSES == ("COMPLETED", "CANCELLED")
