"""Tests for the CompletionProcessor deep module.

The headline test drives the whole workflow through ``run(conn)`` with fakes at
the DraftKings edge and real `NotificationStore` + `ContestDatabase` on an
in-memory sqlite connection, asserting each milestone announces once and stays
silent on a second run (idempotency).
"""

import datetime
import sqlite3

from dk_results.completion_processor import (
    COMPLETED_STATUSES,
    CompletionProcessor,
    CompletionProcessorConfig,
    _canonical_vips,
    _leaderboard_cash_value,
    _parse_start_date,
    _soft_finish_eligible,
    _soft_finish_event_key,
)
from dk_results.notifications.vip_presence import VIP_ABSENT, VIP_PRESENT, VIP_UNKNOWN
from dk_results.persistence.contestdatabase import ContestDatabase

CONTESTS_TABLE_SQL = """
CREATE TABLE contests (
    dk_id INTEGER PRIMARY KEY,
    sport varchar(10) NOT NULL,
    name varchar(50) NOT NULL,
    start_date datetime NOT NULL,
    draft_group INTEGER NOT NULL,
    total_prizes INTEGER NOT NULL,
    entries INTEGER NOT NULL,
    positions_paid INTEGER,
    entry_fee INTEGER NOT NULL,
    entry_count INTEGER NOT NULL,
    max_entry_count INTEGER NOT NULL,
    completed INTEGER NOT NULL DEFAULT 0,
    status TEXT
);
"""


class DummySport:
    name = "NBA"
    sheet_min_entry_fee = 25
    keyword = "%"


class RecordingSender:
    """A BonusSenderPort that records everything sent."""

    def __init__(self):
        self.messages: list[str] = []

    def send_message(self, message: str) -> None:
        self.messages.append(message)


class FakeVipPresence:
    """A presence oracle returning one canned verdict, recording its calls."""

    def __init__(self, verdict: str = VIP_UNKNOWN):
        self._verdict = verdict
        self.calls: list[tuple] = []

    def verdict(self, dk_id: int, start_date: str, vip_names: list[str]) -> str:
        self.calls.append((dk_id, start_date, tuple(vip_names)))
        return self._verdict


class FakeContestResults:
    """A ContestResultsPort serving canned detail / leaderboard payloads."""

    def __init__(self, *, details=None, leaderboards=None, entrants=None):
        # details: dict[dk_id, list-or-single detail payload]; a list is consumed
        # one entry per call so a contest can advance across runs.
        self._details = {k: list(v) if isinstance(v, list) else [v] for k, v in (details or {}).items()}
        self._leaderboards = {k: list(v) if isinstance(v, list) else [v] for k, v in (leaderboards or {}).items()}
        self._entrants = entrants or {}
        self.detail_calls: list[int] = []

    def get_contest_detail(self, dk_id, timeout=None):
        self.detail_calls.append(dk_id)
        queue = self._details[dk_id]
        return queue.pop(0) if len(queue) > 1 else queue[0]

    def get_leaderboard(self, contest_id, timeout=None, session=None):
        queue = self._leaderboards[contest_id]
        return queue.pop(0) if len(queue) > 1 else queue[0]

    def get_contest_entrants_page(self, contest_id, page_no, timeout=None, session=None):
        pages = self._entrants.get(contest_id, [])
        return pages[page_no - 1] if page_no - 1 < len(pages) else ""


def _detail(*, status, completed, positions_paid=10, entries=100):
    return {
        "contestDetail": {
            "payoutSummary": [{"maxPosition": positions_paid}],
            "contestStateDetail": status,
            "maximumEntries": entries,
        }
    }


def _leaderboard_payload(*, top_score=229, cashing_score=185.5, rows=None):
    if rows is None:
        rows = [
            {
                "userName": "FooBar",
                "timeRemaining": 0,
                "fantasyPoints": top_score,
                "winningValue": 100.0,
                "winnings": [{"value": 100.0, "description": "Cash"}],
            },
            {
                "userName": "OtherUser",
                "timeRemaining": 0,
                "fantasyPoints": cashing_score,
                "winningValue": 0.0,
                "winnings": [],
            },
        ]
    return {
        "leader": {"timeRemaining": 0, "fantasyPoints": top_score},
        "lastWinningEntry": {"timeRemaining": 0, "fantasyPoints": cashing_score},
        "leaderBoard": rows,
    }


def _conn_with_table() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute(CONTESTS_TABLE_SQL)
    conn.commit()
    return conn


def _insert_contest(conn, *, dk_id, name, start_date, status, completed=0, draft_group=1, positions_paid=None):
    conn.execute(
        """
        INSERT INTO contests (
            dk_id, sport, name, start_date, draft_group, total_prizes, entries,
            positions_paid, entry_fee, entry_count, max_entry_count, completed, status
        ) VALUES (?, 'NBA', ?, ?, ?, 0, 100, ?, 25, 0, 1, ?, ?)
        """,
        (dk_id, name, start_date, draft_group, positions_paid, completed, status),
    )
    conn.commit()


def _make_config(
    *,
    vips=None,
    warning_schedules=None,
    sport_choices=None,
    spreadsheet_id=None,
    sheet_gid_map=None,
    notifications_enabled=True,
):
    return CompletionProcessorConfig(
        sport_choices=sport_choices if sport_choices is not None else {"NBA": DummySport},
        warning_schedules=warning_schedules if warning_schedules is not None else {"default": []},
        default_warning_schedule=[25],
        sport_emoji={"NBA": "🏀"},
        spreadsheet_id=spreadsheet_id,
        sheet_gid_map=sheet_gid_map or {},
        vips=vips or [],
        notifications_enabled=notifications_enabled,
    )


def _make_processor(conn, *, results, sender=None, presence=None, config=None):
    return CompletionProcessor(
        contest_db=ContestDatabase.from_connection(conn),
        results=results,
        presence=presence,
        bonus_sender=sender,
        config=config or _make_config(),
    )


# ── Headline seam test ───────────────────────────────────────────────────────


def test_live_milestone_announced_then_silent_on_second_run():
    conn = _conn_with_table()
    past = "2024-01-01 00:00:00"
    _insert_contest(conn, dk_id=1, name="Contest1", start_date=past, status="UPCOMING")

    results = FakeContestResults(details={1: _detail(status="LIVE", completed=0)})
    sender = RecordingSender()
    processor = _make_processor(conn, results=results, sender=sender, presence=FakeVipPresence(VIP_UNKNOWN))

    processor.run(conn)
    assert [m.split(":")[0] for m in sender.messages] == ["Contest started"]

    # DB advanced to LIVE, so the transition is no longer "new"; and the live
    # notification is recorded — either way, a second run stays silent.
    processor.run(conn)
    assert len(sender.messages) == 1


def test_disabled_notifications_send_nothing_even_with_sender():
    """A disabled run still advances state but short-circuits every send.

    Story 7: ``notifications_enabled`` is the authority, independent of whether a
    sender is wired. Here a live transition would normally announce, but the
    disabled flag suppresses it while the DB is still advanced to LIVE.
    """
    conn = _conn_with_table()
    _insert_contest(conn, dk_id=1, name="Contest1", start_date="2024-01-01 00:00:00", status="UPCOMING")

    results = FakeContestResults(details={1: _detail(status="LIVE", completed=0)})
    sender = RecordingSender()
    processor = _make_processor(
        conn,
        results=results,
        sender=sender,
        presence=FakeVipPresence(VIP_UNKNOWN),
        config=_make_config(notifications_enabled=False),
    )

    processor.run(conn)

    assert sender.messages == []
    # State sync is not gated: the contest advanced to LIVE.
    row = conn.execute("SELECT status FROM contests WHERE dk_id = 1").fetchone()
    assert row[0] == "LIVE"


def test_completed_milestone_announced_once_after_live():
    conn = _conn_with_table()
    past = "2024-01-01 00:00:00"
    _insert_contest(conn, dk_id=1, name="Contest1", start_date=past, status="LIVE")

    # A prior "live" notification must exist for the completed announcement.
    from dk_results.persistence.notification_store import NotificationStore

    NotificationStore(conn).record_notification(1, "live")

    results = FakeContestResults(details={1: _detail(status="COMPLETED", completed=1)})
    sender = RecordingSender()
    processor = _make_processor(conn, results=results, sender=sender, presence=FakeVipPresence(VIP_UNKNOWN))

    processor.run(conn)
    processor.run(conn)

    assert [m for m in sender.messages if m.startswith("Contest ended")]
    assert sum(m.startswith("Contest ended") for m in sender.messages) == 1


def test_soft_finish_summary_announced_once_then_silent():
    conn = _conn_with_table()
    _insert_contest(conn, dk_id=1, name="Live Contest", start_date="2024-01-01 00:00:00", status="LIVE")

    results = FakeContestResults(
        details={1: _detail(status="LIVE", completed=0)},
        leaderboards={1: _leaderboard_payload()},
    )
    sender = RecordingSender()
    processor = _make_processor(conn, results=results, sender=sender, presence=FakeVipPresence(VIP_UNKNOWN))

    processor.run(conn)
    processor.run(conn)

    soft = [m for m in sender.messages if "soft-finished" in m]
    assert len(soft) == 1
    assert "Top score" in soft[0]
    assert "Cashing score" in soft[0]


def test_soft_finish_resends_updated_when_summary_changes():
    conn = _conn_with_table()
    _insert_contest(conn, dk_id=1, name="Live Contest", start_date="2024-01-01 00:00:00", status="LIVE")

    results = FakeContestResults(
        details={1: _detail(status="LIVE", completed=0)},
        leaderboards={
            1: [
                _leaderboard_payload(top_score=221.5, cashing_score=180.25),
                _leaderboard_payload(top_score=223.0, cashing_score=181.0),
            ]
        },
    )
    sender = RecordingSender()
    processor = _make_processor(conn, results=results, sender=sender, presence=FakeVipPresence(VIP_UNKNOWN))

    processor.run(conn)
    processor.run(conn)

    soft = [m for m in sender.messages if "soft-finished" in m]
    assert len(soft) == 2
    assert "(updated)" not in soft[0]
    assert "(updated)" in soft[1]


def test_warning_announced_once_within_window_then_silent():
    conn = _conn_with_table()
    start = (datetime.datetime.now() + datetime.timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M:%S")
    _insert_contest(conn, dk_id=1, name="Upcoming", start_date=start, status="UPCOMING")

    results = FakeContestResults(details={1: _detail(status="LIVE", completed=0)})
    sender = RecordingSender()
    config = _make_config(warning_schedules={"default": [25]})
    processor = _make_processor(
        conn, results=results, sender=sender, presence=FakeVipPresence(VIP_UNKNOWN), config=config
    )

    processor.run(conn)
    processor.run(conn)

    warnings = [m for m in sender.messages if m.startswith("Contest starting soon")]
    assert len(warnings) == 1
    assert "(25m)" in warnings[0]


# ── Suppression policy ───────────────────────────────────────────────────────


def test_absent_verdict_suppresses_live_announcement():
    conn = _conn_with_table()
    _insert_contest(conn, dk_id=1, name="Contest1", start_date="2024-01-01 00:00:00", status="UPCOMING")

    results = FakeContestResults(details={1: _detail(status="LIVE", completed=0)})
    sender = RecordingSender()
    presence = FakeVipPresence(VIP_ABSENT)
    processor = _make_processor(conn, results=results, sender=sender, presence=presence)

    processor.run(conn)

    assert sender.messages == []
    assert presence.calls  # the policy consulted the oracle


def test_unknown_verdict_allows_soft_finish():
    conn = _conn_with_table()
    _insert_contest(conn, dk_id=1, name="Live Contest", start_date="2024-01-01 00:00:00", status="LIVE")

    results = FakeContestResults(
        details={1: _detail(status="LIVE", completed=0)},
        leaderboards={1: _leaderboard_payload()},
    )
    sender = RecordingSender()
    processor = _make_processor(conn, results=results, sender=sender, presence=FakeVipPresence(VIP_UNKNOWN))

    processor.run(conn)

    assert any("soft-finished" in m for m in sender.messages)


def test_present_verdict_allows_and_no_presence_object_allows():
    conn = _conn_with_table()
    _insert_contest(conn, dk_id=1, name="Contest1", start_date="2024-01-01 00:00:00", status="UPCOMING")
    results = FakeContestResults(details={1: _detail(status="LIVE", completed=0)})

    sender = RecordingSender()
    _make_processor(conn, results=results, sender=sender, presence=FakeVipPresence(VIP_PRESENT)).run(conn)
    assert any(m.startswith("Contest started") for m in sender.messages)

    # A None presence oracle behaves like "unknown": announcements are allowed.
    conn2 = _conn_with_table()
    _insert_contest(conn2, dk_id=2, name="Contest2", start_date="2024-01-01 00:00:00", status="UPCOMING")
    results2 = FakeContestResults(details={2: _detail(status="LIVE", completed=0)})
    sender2 = RecordingSender()
    _make_processor(conn2, results=results2, sender=sender2, presence=None).run(conn2)
    assert any(m.startswith("Contest started") for m in sender2.messages)


# ── State sync runs without a sender ─────────────────────────────────────────


def test_state_sync_updates_db_without_sender():
    conn = _conn_with_table()
    _insert_contest(conn, dk_id=1, name="Contest1", start_date="2024-01-01 00:00:00", status="UPCOMING")

    results = FakeContestResults(details={1: _detail(status="COMPLETED", completed=1, positions_paid=42)})
    processor = _make_processor(conn, results=results, sender=None, presence=None)

    processor.run(conn)

    db = ContestDatabase.from_connection(conn)
    assert db.get_contest_state(1) == ("COMPLETED", 1)
    row = db.get_contest_by_id(1)
    assert row is not None and row.positions_paid == 42


def test_unavailable_results_are_skipped_gracefully():
    conn = _conn_with_table()
    _insert_contest(conn, dk_id=1, name="Contest1", start_date="2024-01-01 00:00:00", status="UPCOMING")

    class BoomResults:
        def get_contest_detail(self, dk_id, timeout=None):
            raise RuntimeError("unavailable")

        def get_leaderboard(self, contest_id, timeout=None, session=None):
            raise RuntimeError("unavailable")

        def get_contest_entrants_page(self, contest_id, page_no, timeout=None, session=None):
            raise RuntimeError("unavailable")

    processor = _make_processor(conn, results=BoomResults(), sender=RecordingSender(), presence=None)
    processor.run(conn)  # must not raise

    # Nothing updated because the read failed.
    assert ContestDatabase.from_connection(conn).get_contest_state(1) == ("UPCOMING", 0)


# ── _get_contest_data ────────────────────────────────────────────────────────


def test_get_contest_data_success_and_bad_status():
    conn = _conn_with_table()
    results = FakeContestResults(details={1: _detail(status="live", completed=0, positions_paid=5, entries=100)})
    processor = _make_processor(conn, results=results, sender=None, presence=None)

    assert processor._get_contest_data(1) == {
        "completed": 0,
        "status": "LIVE",
        "entries": 100,
        "positions_paid": 5,
    }

    bad = FakeContestResults(details={2: _detail(status="POSTPONED", completed=0)})
    processor_bad = _make_processor(conn, results=bad, sender=None, presence=None)
    assert processor_bad._get_contest_data(2) is None


# ── Presentation helpers ─────────────────────────────────────────────────────


def test_format_contest_announcement_relative_time_and_sheet_link():
    conn = _conn_with_table()
    config = _make_config(spreadsheet_id="test-sheet", sheet_gid_map={"NBA": 123})
    processor = _make_processor(conn, results=FakeContestResults(), sender=None, presence=None, config=config)

    now = datetime.datetime.now().replace(microsecond=0)
    start = now + datetime.timedelta(minutes=13, seconds=30)
    msg = processor._format_contest_announcement(
        "Contest starting soon", "NBA", "Test Contest", start.isoformat(sep=" "), 123
    )

    assert "(⏳ 13m)" in msg
    assert "🔗 DK: [123]" in msg
    assert "📊 Sheet: [NBA]" in msg


def test_sport_emoji_default_and_sheet_link_missing():
    conn = _conn_with_table()
    processor = _make_processor(conn, results=FakeContestResults(), sender=None, presence=None)
    assert processor._sport_emoji("UNKNOWN") == "🏟️"
    assert processor._sheet_link("NBA") is None  # no spreadsheet_id configured


# ── Pure helpers ─────────────────────────────────────────────────────────────


def test_parse_start_date_handles_str_and_datetime_and_bad():
    dt = datetime.datetime(2026, 1, 1, 0, 0, 0)
    assert _parse_start_date(dt) is dt
    assert _parse_start_date("2026-01-01 00:00:00") == dt
    assert _parse_start_date("bad-date") is None
    assert _parse_start_date(None) is None


def test_soft_finish_eligible_requires_zero_time_remaining():
    assert _soft_finish_eligible(_leaderboard_payload()) is True
    not_final = _leaderboard_payload()
    not_final["leader"]["timeRemaining"] = 5
    assert _soft_finish_eligible(not_final) is False
    assert _soft_finish_eligible({}) is False


def test_soft_finish_event_key_is_stable_across_equivalent_numbers():
    a = _soft_finish_event_key(sport_name="NBA", dk_id=1, top_score=123, cashing_score=99, vips_cashed=["FooBar"])
    b = _soft_finish_event_key(sport_name="nba", dk_id=1, top_score=123.00, cashing_score=99.0, vips_cashed=["foobar"])
    assert a == b


def test_leaderboard_cash_value_prefers_winning_value_then_sums_cash():
    assert _leaderboard_cash_value({"winningValue": "50"}) == 50
    summed = _leaderboard_cash_value(
        {"winnings": [{"value": 10, "description": "Cash prize"}, {"value": 5, "description": "Ticket"}]}
    )
    assert summed == 10


def test_canonical_vips_dedupes_case_insensitively_and_sorts():
    assert _canonical_vips(["FooBar", "foobar", "Alpha"]) == ["Alpha", "FooBar"]


def test_completed_statuses_constant():
    assert COMPLETED_STATUSES == ("COMPLETED", "CANCELLED")
