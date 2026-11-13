"""Poll-atomic persistence and snapshot reads for standings cashing."""

import logging
import sqlite3
from collections.abc import Callable
from typing import TypeVar, cast, overload

import pytest

from dk_results.persistence.contestdatabase import ContestDatabase, StandingsCashSnapshot, VipCashStatus

_CursorT = TypeVar("_CursorT", bound=sqlite3.Cursor)


class _FailingCursor(sqlite3.Cursor):
    def execute(self, *_args, **_kwargs):
        raise sqlite3.Error("boom")


class _FailingConnection(sqlite3.Connection):
    rolled_back = False

    @overload
    def cursor(self, factory: None = None) -> _FailingCursor: ...
    @overload
    def cursor(self, factory: Callable[[sqlite3.Connection], _CursorT]) -> _CursorT: ...
    def cursor(self, factory=None):
        return (factory or _FailingCursor)(self)

    def rollback(self):
        self.rolled_back = True
        super().rollback()


@pytest.fixture
def contest_db():
    db = ContestDatabase(":memory:")
    db.ensure_schema()
    db.conn.execute(
        "INSERT INTO contests "
        "(dk_id, sport, name, start_date, draft_group, total_prizes, entries, entry_fee, entry_count, max_entry_count) "
        "VALUES (1, 'NBA', 'Contest', '2024-01-01', 1, 1000, 100, 25, 0, 1)"
    )
    db.conn.commit()
    try:
        yield db
    finally:
        db.close()


class _CommitOnFetchCursor(sqlite3.Cursor):
    """Commit a writer after a SELECT starts but before its rows are collected."""

    def fetchall(self):
        connection = cast("_CommitOnFetchConnection", self.connection)
        callback = connection.before_fetch
        if callback is not None:
            connection.before_fetch = None
            callback()
        return super().fetchall()


class _CommitOnFetchConnection(sqlite3.Connection):
    before_fetch: Callable[[], None] | None = None

    @overload
    def cursor(self, factory: None = None) -> _CommitOnFetchCursor: ...
    @overload
    def cursor(self, factory: Callable[[sqlite3.Connection], _CursorT]) -> _CursorT: ...
    def cursor(self, factory=None):
        return super().cursor(factory or _CommitOnFetchCursor)


def test_cash_line_and_vips_are_replaced_as_one_poll(contest_db):
    old_status = VipCashStatus(vip_name="Alice", rank=10, points=100.0)
    new_status = VipCashStatus(vip_name="Alice", rank=20, points=200.0)
    contest_db.persist_standings_cash_snapshot(1, 10, 100.0, [old_status])

    assert contest_db.get_standings_cash_snapshot(1) == StandingsCashSnapshot((10, 100.0), [old_status])

    contest_db.persist_standings_cash_snapshot(1, 20, 200.0, [new_status])

    assert contest_db.get_standings_cash_snapshot(1) == StandingsCashSnapshot((20, 200.0), [new_status])


def test_failed_poll_rolls_back_cash_line_and_vip_rows(caplog, contest_db):
    old_status = VipCashStatus(vip_name="Alice", rank=10, points=100.0)
    contest_db.persist_standings_cash_snapshot(1, 10, 100.0, [old_status])

    with caplog.at_level(logging.ERROR):
        # Duplicate VIP names violate the table's primary key after the cash-line update.
        contest_db.persist_standings_cash_snapshot(
            1, 20, 200.0, [VipCashStatus(vip_name="Alice", rank=20, points=200.0)] * 2
        )

    assert contest_db.get_standings_cash_snapshot(1) == StandingsCashSnapshot((10, 100.0), [old_status])
    assert any("persist_standings_cash_snapshot" in record.message for record in caplog.records)


def test_empty_poll_clears_vips_with_new_cash_line(contest_db):
    contest_db.persist_standings_cash_snapshot(1, 10, 100.0, [VipCashStatus("Alice", 10, 100.0)])

    contest_db.persist_standings_cash_snapshot(1, 20, 200.0, [])

    assert contest_db.get_standings_cash_snapshot(1) == StandingsCashSnapshot((20, 200.0), [])


def test_snapshot_read_returns_complete_old_or_new_poll_across_commit(tmp_path):
    path = str(tmp_path / "polls.db")
    writer = ContestDatabase(path)
    writer.ensure_schema()
    writer.conn.execute(
        "INSERT INTO contests "
        "(dk_id, sport, name, start_date, draft_group, total_prizes, entries, entry_fee, entry_count, max_entry_count) "
        "VALUES (1, 'NBA', 'Contest', '2024-01-01', 1, 1000, 100, 25, 0, 1)"
    )
    writer.conn.commit()
    reader = ContestDatabase(path)
    try:
        old_status = VipCashStatus("Alice", 10, 100.0)
        new_status = VipCashStatus("Alice", 20, 200.0)
        writer.persist_standings_cash_snapshot(1, 10, 100.0, [old_status])
        first = reader.get_standings_cash_snapshot(1)
        writer.persist_standings_cash_snapshot(1, 20, 200.0, [new_status])
        second = reader.get_standings_cash_snapshot(1)

        assert first == StandingsCashSnapshot((10, 100.0), [old_status])
        assert second == StandingsCashSnapshot((20, 200.0), [new_status])
    finally:
        reader.close()
        writer.close()


def test_snapshot_read_stays_consistent_when_writer_commits_mid_query(tmp_path):
    path = str(tmp_path / "concurrent-poll.db")
    writer = ContestDatabase(path)
    writer.conn.execute("PRAGMA journal_mode=WAL")
    writer.ensure_schema()
    writer.conn.execute(
        "INSERT INTO contests "
        "(dk_id, sport, name, start_date, draft_group, total_prizes, entries, entry_fee, entry_count, max_entry_count) "
        "VALUES (1, 'NBA', 'Contest', '2024-01-01', 1, 1000, 100, 25, 0, 1)"
    )
    writer.conn.commit()
    old_status = VipCashStatus("Alice", 10, 100.0)
    new_status = VipCashStatus("Alice", 20, 200.0)
    writer.persist_standings_cash_snapshot(1, 10, 100.0, [old_status])
    reader_conn = sqlite3.connect(path, factory=_CommitOnFetchConnection)
    reader = ContestDatabase.from_connection(reader_conn)
    reader_conn.before_fetch = lambda: writer.persist_standings_cash_snapshot(1, 20, 200.0, [new_status])
    try:
        during_commit = reader.get_standings_cash_snapshot(1)

        assert during_commit == StandingsCashSnapshot((10, 100.0), [old_status])
        assert reader.get_standings_cash_snapshot(1) == StandingsCashSnapshot((20, 200.0), [new_status])
    finally:
        reader.close()
        writer.close()


@pytest.mark.parametrize(
    ("method", "expected", "rolls_back"),
    [
        ("get_standings_cash_snapshot", None, False),
        ("persist_standings_cash_snapshot", None, True),
    ],
)
def test_snapshot_database_methods_guard_sqlite_errors(method, expected, rolls_back):
    conn = sqlite3.connect(":memory:", factory=_FailingConnection)
    try:
        db = ContestDatabase.from_connection(conn)
        if method == "get_standings_cash_snapshot":
            result = db.get_standings_cash_snapshot(1)
        else:
            result = db.persist_standings_cash_snapshot(1, 1, 1.0, [])

        assert result == expected
        assert conn.rolled_back is rolls_back
    finally:
        conn.close()
