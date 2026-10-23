"""Each CompletionProcessor milestone announces once, then stays silent on the next run.

The headline tests drive the whole workflow through ``run(conn)`` with fakes at the
DraftKings edge and a real `NotificationStore` + `ContestDatabase` on an in-memory
sqlite connection.
"""

import datetime

from dk_results.notifications.vip_presence import VIP_PRESENT, VIP_UNKNOWN


def test_live_milestone_announced_then_silent_on_second_run(
    conn, sender, insert_contest, detail, make_results, make_presence, make_processor, bare_text
):
    insert_contest(status="UPCOMING")
    processor = make_processor(
        results=make_results(detail=detail(status="LIVE")), sender=sender, presence=make_presence(VIP_PRESENT)
    )

    processor.run(conn)
    assert sender.messages == [bare_text("Contest started")]

    # DB advanced to LIVE, so the transition is no longer "new"; and the live
    # notification is recorded — either way, a second run stays silent.
    processor.run(conn)
    assert len(sender.messages) == 1


def test_completed_milestone_announced_once_after_live(
    conn, sender, insert_contest, record, detail, make_results, make_presence, make_processor, bare_text
):
    insert_contest(status="LIVE")
    # A prior "live" notification must exist for the completed announcement.
    record(1, "live")
    processor = make_processor(
        results=make_results(detail=detail(status="COMPLETED")), sender=sender, presence=make_presence(VIP_UNKNOWN)
    )

    processor.run(conn)
    processor.run(conn)

    assert sender.messages == [bare_text("Contest ended")]


def test_warning_announced_once_within_window_then_silent(
    conn,
    sender,
    scenario,
    clock_at,
    insert_contest,
    detail,
    make_results,
    make_presence,
    make_processor,
    bare_text,
):
    start = datetime.datetime.fromisoformat(scenario.far_start)
    insert_contest(name="Upcoming", start_date=scenario.far_start, status="UPCOMING")
    processor = make_processor(
        results=make_results(detail=detail(status="LIVE")),
        sender=sender,
        presence=make_presence(VIP_PRESENT),
        warning_schedule=[25],
        now=clock_at(start - datetime.timedelta(minutes=10)),
    )

    processor.run(conn)
    processor.run(conn)

    expected = bare_text("Contest starting soon (25m)", name="Upcoming", when=f"{scenario.far_start} (⏳ 10m)")
    assert sender.messages == [expected]
