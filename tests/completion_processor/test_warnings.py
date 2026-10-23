"""CompletionProcessor starting-soon warnings: window, schedule and contest choice."""

import datetime
import logging

import pytest

from dk_results.completion_processor import CompletionProcessor, CompletionProcessorConfig
from dk_results.notifications.vip_presence import VIP_PRESENT
from dk_results.persistence.contestdatabase import ContestDatabase

START = datetime.datetime(2099, 6, 1, 20, 0, 0)


def _at(**delta):
    return START - datetime.timedelta(**delta)


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
def test_warning_is_sent_only_while_the_start_is_inside_the_window(run_warning, now, sent):
    assert bool(run_warning(at=now).messages) is sent


def test_warning_with_a_timezone_aware_start_is_measured_in_that_zone(run_warning):
    start = "2099-06-01T20:00:00+00:00"
    now = datetime.datetime(2099, 6, 1, 19, 35, tzinfo=datetime.timezone.utc)
    sender = run_warning(at=now, start=start)
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
def test_warning_schedule_is_looked_up_by_lowercase_sport_name(
    run_warning, scenario, stored_events, schedules, fallback, kinds
):
    run_warning(at=_at(minutes=40), warning_schedules=schedules, default_warning_schedule=fallback)
    assert stored_events(scenario.dk_id) == kinds


def test_warning_already_announced_is_not_repeated(
    conn, sender, scenario, clock_at, insert_contest, record, make_results, make_processor, caplog
):
    insert_contest(dk_id=scenario.dk_id, name="Main", start_date=scenario.far_start)
    record(scenario.dk_id, "warning:25")
    processor = make_processor(
        results=make_results(), sender=sender, warning_schedule=[25], now=clock_at(_at(minutes=20))
    )
    with caplog.at_level(logging.DEBUG):
        processor.run(conn)
    assert sender.messages == []
    assert "warning already sent for NBA dk_id=42 (25m)" in caplog.messages


@pytest.mark.parametrize(
    ("schedules", "source"),
    [({"nba": [25]}, "sport"), ({"default": [25]}, "default")],
)
def test_warning_schedule_resolution_is_logged_with_its_source(run_warning, caplog, schedules, source):
    with caplog.at_level(logging.DEBUG):
        run_warning(warning_schedules=schedules)
    assert f"warning schedule for NBA: [25] (source={source})" in caplog.messages


@pytest.fixture
def seed_contests(insert_contest):
    rows = [
        (1, "Main Event", 100, "2099-06-01 20:00:00"),
        (2, "Satellite", 30, "2099-06-01 19:40:00"),
        (3, "Main small", 30, "2099-06-01 19:50:00"),
        (4, "Big Other", 100, "2099-06-01 19:45:00"),
    ]
    for dk_id, name, fee, start in rows:
        insert_contest(dk_id=dk_id, name=name, entry_fee=fee, start_date=start)


@pytest.fixture
def warn_with_sport(conn, sender, clock_at, detail, make_results, make_processor, seed_contests):
    def run(sport):
        results = make_results(detail=detail(status="UPCOMING"))
        now = clock_at(datetime.datetime(2099, 6, 1, 19, 30))
        make_processor(
            results=results, sender=sender, sport_choices={"NBA": sport}, warning_schedule=[60], now=now
        ).run(conn)
        return sender.messages

    return run


def test_warning_targets_the_next_contest_matching_the_sports_fee_and_keyword(
    warn_with_sport, make_sport, stored_events
):
    messages = warn_with_sport(make_sport("NBA", fee=50, keyword="%Main%"))
    assert [m.splitlines()[0] for m in messages] == ["Contest starting soon (60m): 🏀 NBA — Main Event"]
    assert stored_events(1) == ["warning:60"]


def test_warning_falls_back_to_the_next_contest_when_none_matches(warn_with_sport, make_sport):
    messages = warn_with_sport(make_sport("NBA", fee=500, keyword="%Main%"))
    assert [m.splitlines()[0] for m in messages] == ["Contest starting soon (60m): 🏀 NBA — Satellite"]


def test_warning_waits_until_the_contest_is_inside_its_window(
    conn, sender, scenario, clock_at, insert_contest, detail, make_results, make_presence, make_processor
):
    insert_contest(start_date=scenario.far_start)
    processor = make_processor(
        results=make_results(detail=detail(status="LIVE")),
        sender=sender,
        presence=make_presence(VIP_PRESENT),
        warning_schedule=[25],
        now=clock_at(_at(minutes=120)),
    )
    processor.run(conn)
    assert sender.messages == []


def test_warning_with_an_unparseable_start_date_is_skipped(
    conn, sender, insert_contest, detail, make_results, make_presence, make_processor
):
    insert_contest(start_date="not a date")
    processor = make_processor(
        results=make_results(detail=detail(status="UPCOMING")),
        sender=sender,
        presence=make_presence(VIP_PRESENT),
        warning_schedule=[25],
    )
    processor.run(conn)
    assert sender.messages == []


def test_warning_schedule_is_resolved_once_per_sport_name(
    conn,
    sender,
    scenario,
    clock_at,
    insert_contest,
    detail,
    make_results,
    make_presence,
    make_sport,
    make_processor,
    bare_text,
    caplog,
):
    # Two sport keys that resolve to one sport name share one schedule lookup.
    insert_contest(start_date=scenario.far_start)
    sport = make_sport("NBA")
    processor = make_processor(
        results=make_results(detail=detail(status="LIVE")),
        sender=sender,
        presence=make_presence(VIP_PRESENT),
        sport_choices={"NBA": sport, "NBA2": sport},
        warning_schedule=[25],
        now=clock_at(_at(minutes=10)),
    )
    with caplog.at_level(logging.DEBUG):
        processor.run(conn)
    assert caplog.messages.count("warning schedule for NBA: [25] (source=default)") == 1
    assert sender.messages == [bare_text("Contest starting soon (25m)", when=f"{scenario.far_start} (⏳ 10m)")]


def test_the_system_clock_is_used_when_no_clock_is_injected(
    conn, sender, insert_contest, detail, make_results, make_sport
):
    start = datetime.datetime.now() + datetime.timedelta(minutes=10)
    insert_contest(start_date=start.strftime("%Y-%m-%d %H:%M:%S"))
    config = CompletionProcessorConfig(
        sport_choices={"NBA": make_sport("NBA")},
        warning_schedules={"default": [25]},
        default_warning_schedule=[25],
        sport_emoji={"NBA": "🏀"},
        spreadsheet_id=None,
        sheet_gid_map={},
        vips=[],
    )
    processor = CompletionProcessor(
        contest_db=ContestDatabase.from_connection(conn),
        results=make_results(detail=detail(status="UPCOMING")),
        presence=None,
        bonus_sender=sender,
        config=config,
    )

    processor.run(conn)

    assert [m.splitlines()[0] for m in sender.messages] == ["Contest starting soon (25m): 🏀 NBA — Contest1"]
