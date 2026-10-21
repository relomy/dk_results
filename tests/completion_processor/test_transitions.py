"""The live and completed transitions CompletionProcessor announces after a state sync."""

import logging

import pytest

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
    insert_contest, record, run_sync, stored_events, status, completed, positions_paid, reported, announced
):
    insert_contest(status=status, completed=completed, positions_paid=positions_paid)
    record(1, "live")
    messages = run_sync(reported)
    assert [m.split(":")[0] for m in messages] == (["Contest ended"] if announced else [])
    assert stored_events() == (["live", "completed"] if announced else ["live"])


def test_completed_notification_already_sent_is_logged_with_the_contest(insert_contest, record, run_sync, caplog):
    insert_contest(status="LIVE")
    record(1, "live")
    record(1, "completed")
    with caplog.at_level(logging.INFO):
        assert run_sync("COMPLETED") == []
    assert "completed notification already sent for NBA dk_id=1" in caplog.messages


def test_completed_without_a_live_announcement_is_skipped_and_logged(insert_contest, run_sync, caplog):
    insert_contest(status="LIVE")
    with caplog.at_level(logging.INFO):
        assert run_sync("COMPLETED") == []
    assert "skipping completed notification for NBA dk_id=1; live notification missing" in caplog.messages


def test_live_transition_already_announced_is_not_repeated(insert_contest, record, run_sync, caplog):
    insert_contest()
    record(1, "live")
    with caplog.at_level(logging.INFO):
        assert run_sync("LIVE") == []
    assert "live notification already sent for NBA dk_id=1" in caplog.messages


def test_live_is_announced_only_for_the_sports_primary_live_contest(insert_contest, run_sync, stored_events):
    insert_contest(dk_id=1, draft_group=1, entry_fee=100, status="LIVE", positions_paid=10)
    insert_contest(dk_id=2, draft_group=2, entry_fee=25, status="UPCOMING")
    assert run_sync() == []
    assert stored_events(2) == []


def test_primary_live_contest_follows_the_sports_entry_fee_and_keyword(insert_contest, run_sync, make_sport):
    insert_contest(dk_id=1, draft_group=1, name="Main A", entry_fee=50, entries=10, status="UPCOMING")
    insert_contest(dk_id=2, draft_group=2, name="Other", entry_fee=100, status="LIVE", positions_paid=10)
    messages = run_sync(sport_choices={"NBA": make_sport("NBA", fee=50, keyword="%Main%")})
    assert [m.splitlines()[0] for m in messages] == ["Contest started: 🏀 NBA — Main A"]
