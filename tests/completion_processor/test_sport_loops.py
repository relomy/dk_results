"""CompletionProcessor keeps going to the next sport after one sport is skipped.

Each case puts a skippable sport first and a healthy one second, then expects
exactly the healthy sport's announcement.
"""

import logging

import pytest

from dk_results.notifications.vip_presence import VIP_ABSENT, VIP_PRESENT

# Each case is the keyword arguments of ``soft_finish_pair`` that spoil NBA's (dk_id 1) turn.
SOFT_FINISH_SKIPS = {
    "no-live-contest": {"first": False},
    "detail-unavailable": {"detail_errors": {1: ValueError("boom")}},
    "completed-mid-run": {"statuses": {1: ["LIVE", "COMPLETED"]}},
    "vip-absent": {"absent": {1}},
    "leaderboard-fails": {"leaderboard_errors": {1: RuntimeError("down")}},
}


@pytest.fixture
def sports(make_sport):
    return {"NBA": make_sport("NBA"), "MLB": make_sport("MLB")}


@pytest.fixture
def soft_finish_pair(
    conn, sender, sports, insert_contest, detail, leaderboard, make_results, make_presence, make_processor
):
    def run(*, first=True, absent=(), statuses=None, detail_errors=None, leaderboard_errors=None):
        """A LIVE contest per sport (NBA first); returns what was sent."""
        if first:
            insert_contest(dk_id=1, sport="NBA", name="First", status="LIVE")
        insert_contest(dk_id=2, sport="MLB", name="Second", status="LIVE")
        details = {dk_id: [detail(status=s) for s in seq] for dk_id, seq in (statuses or {}).items()}
        results = make_results(
            detail=detail(status="LIVE"),
            leaderboard=leaderboard(),
            details_by_id=details | (detail_errors or {}),
            leaderboards_by_id=leaderboard_errors,
        )
        presence = make_presence(VIP_PRESENT, by_id={dk_id: VIP_ABSENT for dk_id in absent})
        make_processor(results=results, sender=sender, presence=presence if absent else None, sport_choices=sports).run(
            conn
        )
        return sender.messages

    return run


@pytest.mark.parametrize("skip", SOFT_FINISH_SKIPS.values(), ids=SOFT_FINISH_SKIPS.keys())
def test_soft_finish_moves_on_to_the_next_sport(soft_finish_pair, skip):
    messages = soft_finish_pair(**skip)
    assert len(messages) == 1
    assert messages[0].startswith("Contest soft-finished: ")
    assert "MLB — Second" in messages[0]


def test_soft_finish_logs_a_vip_absent_skip(soft_finish_pair, caplog):
    with caplog.at_level(logging.INFO):
        soft_finish_pair(absent={1})
    assert "skipping soft-finish notification for NBA dk_id=1; vip_presence=absent" in caplog.messages


def test_soft_finish_logs_a_failed_evaluation(soft_finish_pair, caplog):
    with caplog.at_level(logging.WARNING):
        soft_finish_pair(leaderboard_errors={1: RuntimeError("down")})
    [failure] = [r for r in caplog.records if r.getMessage() == "soft-finish evaluation failed for NBA dk_id=1"]
    assert failure.exc_info is not None


@pytest.fixture
def warning_pair(conn, sender, sports, scenario, clock_at, insert_contest, detail, make_results, make_processor):
    def run(*, nba_start=None):
        """NBA's next contest is ``nba_start`` (or absent); MLB's opens its window now."""
        if nba_start:
            insert_contest(dk_id=1, sport="NBA", name="First", start_date=nba_start)
        insert_contest(dk_id=2, sport="MLB", name="Second", start_date=scenario.far_start)
        results = make_results(detail=detail(status="UPCOMING"))
        now = clock_at(scenario.far_now)
        make_processor(results=results, sender=sender, sport_choices=sports, warning_schedule=[25], now=now).run(conn)
        return sender.messages

    return run


@pytest.mark.parametrize("nba_start", [None, "not a date"], ids=["no-upcoming-contest", "unparseable-start-date"])
def test_warnings_move_on_to_the_next_sport(warning_pair, nba_start):
    messages = warning_pair(nba_start=nba_start)
    assert len(messages) == 1
    assert messages[0].startswith("Contest starting soon (25m): ")
    assert "MLB — Second" in messages[0]
