import datetime
import sqlite3

import pytest
from classes.contest import Contest
from classes.contestdatabase import ContestDatabase


@pytest.fixture
def contest_db():
    db = ContestDatabase(":memory:")
    db.create_table()
    try:
        yield db
    finally:
        db.close()


def _insert_contest(
    db: ContestDatabase,
    *,
    dk_id: int,
    sport: str = "NBA",
    name: str = "Contest",
    start_date: str = "2024-01-01 00:00:00",
    draft_group: int = 1,
    total_prizes: int = 1000,
    entries: int = 100,
    positions_paid: int | None = None,
    entry_fee: int = 25,
    entry_count: int = 0,
    max_entry_count: int = 1,
    completed: int = 0,
    status: str | None = "LIVE",
):
    db.conn.execute(
        """
        INSERT INTO contests (
            dk_id, sport, name, start_date, draft_group, total_prizes,
            entries, positions_paid, entry_fee, entry_count, max_entry_count,
            completed, status
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            dk_id,
            sport,
            name,
            start_date,
            draft_group,
            total_prizes,
            entries,
            positions_paid,
            entry_fee,
            entry_count,
            max_entry_count,
            completed,
            status,
        ),
    )
    db.conn.commit()


def test_get_live_contest_prefers_entry_fee_at_or_above_min(contest_db):
    _insert_contest(contest_db, dk_id=1, entry_fee=30, entries=150)
    _insert_contest(contest_db, dk_id=2, entry_fee=10, entries=500)

    row = contest_db.get_live_contest("NBA", entry_fee=25)

    assert row[0] == 1  # dk_id


def test_get_live_contest_falls_back_to_highest_below_min(contest_db):
    _insert_contest(contest_db, dk_id=3, entry_fee=10, entries=200)
    _insert_contest(contest_db, dk_id=4, entry_fee=5, entries=400)

    row = contest_db.get_live_contest("NBA", entry_fee=25)

    assert row[0] == 3


def test_get_live_contest_returns_none_when_no_rows(contest_db):
    assert contest_db.get_live_contest("NBA", entry_fee=25) is None


def test_get_live_contest_is_deterministic_on_ties(contest_db):
    base_time = datetime.datetime(2024, 1, 1, 12, 0, 0)
    _insert_contest(
        contest_db,
        dk_id=5,
        entry_fee=20,
        entries=100,
        start_date=(base_time - datetime.timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S"),
    )
    _insert_contest(
        contest_db,
        dk_id=6,
        entry_fee=20,
        entries=100,
        start_date=base_time.strftime("%Y-%m-%d %H:%M:%S"),
    )

    row = contest_db.get_live_contest("NBA", entry_fee=25)

    assert row[0] == 6


def test_get_live_contests_uses_fallback_per_sport(contest_db):
    _insert_contest(contest_db, dk_id=10, sport="NBA", entry_fee=10, entries=200)
    _insert_contest(contest_db, dk_id=11, sport="NFL", entry_fee=30, entries=100)

    rows = contest_db.get_live_contests(sports=["NBA", "NFL"], entry_fee=25)

    assert rows == [
        (10, "Contest", 1, None, "2024-01-01 00:00:00", "NBA"),
        (11, "Contest", 1, None, "2024-01-01 00:00:00", "NFL"),
    ]


def test_get_live_contests_discovers_sports_when_not_provided(contest_db):
    _insert_contest(contest_db, dk_id=12, sport="NBA", entry_fee=20, entries=50)

    rows = contest_db.get_live_contests(entry_fee=25)

    assert rows == [
        (12, "Contest", 1, None, "2024-01-01 00:00:00", "NBA"),
    ]


def test_sync_draft_group_start_dates_updates_only_changed_groups(contest_db):
    _insert_contest(contest_db, dk_id=1, draft_group=10, start_date="2024-01-01 00:00:00")
    _insert_contest(contest_db, dk_id=2, draft_group=10, start_date="2024-01-01 00:00:00")
    _insert_contest(contest_db, dk_id=3, draft_group=20, start_date="2024-01-02 00:00:00")

    updates = contest_db.sync_draft_group_start_dates(
        {
            10: datetime.datetime(2024, 1, 1, 0, 0, 0),
            20: datetime.datetime(2024, 1, 3, 12, 0, 0),
        }
    )

    assert updates == 1

    rows = list(contest_db.conn.execute("SELECT dk_id, start_date FROM contests ORDER BY dk_id"))
    assert rows == [
        (1, "2024-01-01 00:00:00"),
        (2, "2024-01-01 00:00:00"),
        (3, "2024-01-03 12:00:00"),
    ]


def _contest_payload(dk_id: int):
    return {
        "sd": "1700000000000",
        "n": "Contest",
        "id": dk_id,
        "dg": 1,
        "po": 0,
        "m": 0,
        "a": 5,
        "ec": 0,
        "mec": 1,
        "attr": {"IsDoubleUp": True, "IsGuaranteed": True},
        "gameType": "Classic",
        "gameTypeId": 1,
    }


def test_compare_contests_empty_returns(contest_db):
    assert contest_db.compare_contests([]) == []


def test_compare_contests_filters_existing(contest_db):
    contest = Contest(_contest_payload(101), "NBA")
    contest_db.insert_contests([contest])

    contests = [
        Contest(_contest_payload(101), "NBA"),
        Contest(_contest_payload(202), "NBA"),
    ]
    assert contest_db.compare_contests(contests) == [202]


def test_insert_contests_writes_rows(contest_db):
    contests = [Contest(_contest_payload(303), "NBA")]
    contest_db.insert_contests(contests)
    rows = list(contest_db.conn.execute("SELECT dk_id FROM contests"))
    assert rows == [(303,)]


def test_sync_draft_group_start_dates_empty_input(contest_db):
    assert contest_db.sync_draft_group_start_dates({}) == 0


def test_sync_draft_group_start_dates_no_rows(contest_db):
    updates = contest_db.sync_draft_group_start_dates({10: datetime.datetime.now()})
    assert updates == 0


def test_sync_draft_group_start_dates_skips_none(contest_db):
    _insert_contest(
        contest_db,
        dk_id=1,
        draft_group=10,
        start_date="2024-01-01 00:00:00",
    )

    updates = contest_db.sync_draft_group_start_dates({10: None})

    assert updates == 0
    row = contest_db.conn.execute("SELECT start_date FROM contests WHERE dk_id=1").fetchone()
    assert row == ("2024-01-01 00:00:00",)


def test_sync_draft_group_start_dates_handles_invalid_existing_date(contest_db):
    insert_sql = (
        "INSERT INTO contests (dk_id, sport, name, start_date, draft_group, "
        "total_prizes, entries, entry_fee, entry_count, max_entry_count, completed) "
        "VALUES (1, 'NBA', 'Contest', 'bad-date', 10, 0, 0, 5, 0, 1, 0)"
    )
    contest_db.conn.execute(insert_sql)
    contest_db.conn.commit()

    updates = contest_db.sync_draft_group_start_dates({10: datetime.datetime(2024, 1, 2, 0, 0, 0)})

    assert updates == 1


def test_get_live_contest_sqlite_error(monkeypatch):
    db = ContestDatabase(":memory:")

    class BoomCursor:
        def execute(self, *_args, **_kwargs):
            raise sqlite3.Error("boom")

    class BoomConn:
        def cursor(self):
            return BoomCursor()

    db.conn = BoomConn()
    assert db.get_live_contest("NBA") is None


def test_get_live_contests_sqlite_error(monkeypatch):
    db = ContestDatabase(":memory:")

    class BoomCursor:
        def execute(self, *_args, **_kwargs):
            raise sqlite3.Error("boom")

    class BoomConn:
        def cursor(self):
            return BoomCursor()

    db.conn = BoomConn()
    assert db.get_live_contests() == []


def test_get_next_upcoming_contest_returns_row(contest_db):
    future = (datetime.datetime.now() + datetime.timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
    insert_sql = (
        "INSERT INTO contests (dk_id, sport, name, start_date, draft_group, "
        "total_prizes, entries, entry_fee, entry_count, max_entry_count, completed) "
        "VALUES (1, 'NBA', 'Contest', ?, 10, 0, 0, 25, 0, 1, 0)"
    )
    contest_db.conn.execute(
        insert_sql,
        (future,),
    )
    contest_db.conn.commit()

    row = contest_db.get_next_upcoming_contest("NBA")
    assert row[0] == 1


def test_get_next_upcoming_contest_any_returns_row(contest_db):
    future = (datetime.datetime.now() + datetime.timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
    insert_sql = (
        "INSERT INTO contests (dk_id, sport, name, start_date, draft_group, "
        "total_prizes, entries, entry_fee, entry_count, max_entry_count, completed) "
        "VALUES (2, 'NBA', 'Contest', ?, 11, 0, 0, 25, 0, 1, 0)"
    )
    contest_db.conn.execute(
        insert_sql,
        (future,),
    )
    contest_db.conn.commit()

    row = contest_db.get_next_upcoming_contest_any("NBA")
    assert row[0] == 2


def test_get_next_upcoming_contest_sqlite_error(monkeypatch):
    db = ContestDatabase(":memory:")

    class BoomCursor:
        def execute(self, *_args, **_kwargs):
            raise sqlite3.Error("boom")

    class BoomConn:
        def cursor(self):
            return BoomCursor()

    db.conn = BoomConn()
    assert db.get_next_upcoming_contest("NBA") is None


def test_get_next_upcoming_contest_any_sqlite_error(monkeypatch):
    db = ContestDatabase(":memory:")

    class BoomCursor:
        def execute(self, *_args, **_kwargs):
            raise sqlite3.Error("boom")

    class BoomConn:
        def cursor(self):
            return BoomCursor()

    db.conn = BoomConn()
    assert db.get_next_upcoming_contest_any("NBA") is None


def test_get_contest_by_id_returns_row(contest_db):
    _insert_contest(contest_db, dk_id=55, sport="NBA", entry_fee=25, entries=123)
    row = contest_db.get_contest_by_id(55)

    assert row == (55, "Contest", 1, None, "2024-01-01 00:00:00", 25, 123)


def test_get_live_contest_candidates_returns_stable_order(contest_db):
    _insert_contest(
        contest_db,
        dk_id=101,
        sport="NBA",
        entry_fee=10,
        entries=200,
        start_date="2024-01-01 01:00:00",
    )
    _insert_contest(
        contest_db,
        dk_id=102,
        sport="NBA",
        entry_fee=30,
        entries=100,
        start_date="2024-01-01 01:00:00",
    )
    _insert_contest(
        contest_db,
        dk_id=103,
        sport="NBA",
        entry_fee=30,
        entries=150,
        start_date="2024-01-01 01:00:00",
    )

    rows = contest_db.get_live_contest_candidates("NBA", entry_fee=25, limit=5)
    assert rows == [
        (103, "Contest", 30, "2024-01-01 01:00:00", 150, 0),
        (102, "Contest", 30, "2024-01-01 01:00:00", 100, 0),
        (101, "Contest", 10, "2024-01-01 01:00:00", 200, 1),
    ]
