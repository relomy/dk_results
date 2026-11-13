"""Poll-atomic persistence and snapshot reads for standings cashing."""

import logging
import sqlite3
import threading
from collections.abc import Callable
from typing import TypeVar, cast, overload

from persistence.builders import insert_contest

from dk_results.persistence.contestdatabase import ContestDatabase, StandingsCashSnapshot, VipCashStatus

_CursorT = TypeVar("_CursorT", bound=sqlite3.Cursor)


class _PausedWriterCursor(sqlite3.Cursor):
    def execute(self, sql, parameters=()):
        result = super().execute(sql, parameters)
        connection = cast(_PausedWriterConnection, self.connection)
        if sql.lstrip().upper().startswith('UPDATE "CONTESTS"'):
            connection.after_cash_line_update()
        return result


class _PausedWriterConnection(sqlite3.Connection):
    after_cash_line_update: Callable[[], None] = staticmethod(lambda: None)

    @overload
    def cursor(self, factory: None = None) -> _PausedWriterCursor: ...
    @overload
    def cursor(self, factory: Callable[[sqlite3.Connection], _CursorT]) -> _CursorT: ...
    def cursor(self, factory=None):
        return super().cursor(factory or _PausedWriterCursor)


class _InterleavingReaderCursor(sqlite3.Cursor):
    statement: str | None = None

    def execute(self, sql, parameters=()):
        self.statement = sql
        return super().execute(sql, parameters)

    def fetchone(self):
        row = super().fetchone()
        connection = cast(_InterleavingReaderConnection, self.connection)
        sql = self.statement
        if sql is not None and 'FROM "CONTESTS"' in sql.upper() and "JOIN" not in sql.upper():
            self.close()
            connection.after_cash_line_read()
        return row


class _InterleavingReaderConnection(sqlite3.Connection):
    after_cash_line_read: Callable[[], None] = staticmethod(lambda: None)

    @overload
    def cursor(self, factory: None = None) -> _InterleavingReaderCursor: ...
    @overload
    def cursor(self, factory: Callable[[sqlite3.Connection], _CursorT]) -> _CursorT: ...
    def cursor(self, factory=None):
        return super().cursor(factory or _InterleavingReaderCursor)


def test_cash_line_and_vips_are_replaced_as_one_poll(contest_db_with_contest):
    contest_db = contest_db_with_contest
    old_status = VipCashStatus(vip_name="Alice", rank=10, points=100.0)
    new_status = VipCashStatus(vip_name="Alice", rank=20, points=200.0)
    contest_db.persist_standings_cash_snapshot(1, 10, 100.0, [old_status])

    assert contest_db.get_standings_cash_snapshot(1) == StandingsCashSnapshot((10, 100.0), [old_status])

    contest_db.persist_standings_cash_snapshot(1, 20, 200.0, [new_status])

    assert contest_db.get_standings_cash_snapshot(1) == StandingsCashSnapshot((20, 200.0), [new_status])


def test_failed_poll_rolls_back_cash_line_and_vip_rows(caplog, contest_db_with_contest):
    contest_db = contest_db_with_contest
    old_status = VipCashStatus(vip_name="Alice", rank=10, points=100.0)
    contest_db.persist_standings_cash_snapshot(1, 10, 100.0, [old_status])

    with caplog.at_level(logging.ERROR):
        # Duplicate VIP names violate the table's primary key after the cash-line update.
        contest_db.persist_standings_cash_snapshot(
            1, 20, 200.0, [VipCashStatus(vip_name="Alice", rank=20, points=200.0)] * 2
        )

    assert contest_db.get_standings_cash_snapshot(1) == StandingsCashSnapshot((10, 100.0), [old_status])
    assert caplog.messages == ["sqlite error in persist_standings_cash_snapshot()"]


def test_empty_poll_clears_vips_with_new_cash_line(contest_db_with_contest):
    contest_db = contest_db_with_contest
    contest_db.persist_standings_cash_snapshot(1, 10, 100.0, [VipCashStatus("Alice", 10, 100.0)])

    contest_db.persist_standings_cash_snapshot(1, 20, 200.0, [])

    assert contest_db.get_standings_cash_snapshot(1) == StandingsCashSnapshot((20, 200.0), [])


def test_snapshot_read_returns_complete_old_or_new_poll_across_commit(tmp_path):
    path = str(tmp_path / "polls.db")
    writer = ContestDatabase(path)
    writer.ensure_schema()
    insert_contest(writer, dk_id=1)
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


def test_reader_sees_old_complete_poll_while_default_journal_writer_is_paused(tmp_path):
    path = str(tmp_path / "paused-poll.db")
    writer_conn = sqlite3.connect(path, factory=_PausedWriterConnection, check_same_thread=False)
    writer = ContestDatabase.from_connection(writer_conn)
    writer.ensure_schema()
    insert_contest(writer, dk_id=1)
    old_status = VipCashStatus("Alice", 10, 100.0)
    new_status = VipCashStatus("Alice", 20, 200.0)
    writer.persist_standings_cash_snapshot(1, 10, 100.0, [old_status])
    reader_conn = sqlite3.connect(path, factory=_InterleavingReaderConnection)
    reader = ContestDatabase.from_connection(reader_conn)
    update_finished = threading.Event()
    continue_writer = threading.Event()
    writer_finished = threading.Event()

    def pause_after_update() -> None:
        update_finished.set()
        continue_writer.wait(timeout=5)

    writer_conn.after_cash_line_update = pause_after_update
    writer_result = []

    def publish_new_poll() -> None:
        writer_result.append(writer.persist_standings_cash_snapshot(1, 20, 200.0, [new_status]))
        writer_finished.set()

    writer_thread = threading.Thread(target=publish_new_poll)
    try:
        assert reader.conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "delete"

        def let_writer_commit_between_legacy_reads() -> None:
            continue_writer.set()
            assert writer_finished.wait(timeout=5)

        reader_conn.after_cash_line_read = let_writer_commit_between_legacy_reads
        writer_thread.start()
        assert update_finished.wait(timeout=5)
        during_write = reader.get_standings_cash_snapshot(1)
        continue_writer.set()
        writer_thread.join(timeout=5)

        assert not writer_thread.is_alive()
        assert during_write == StandingsCashSnapshot((10, 100.0), [old_status])
        assert writer_result == [None]
        assert reader.get_standings_cash_snapshot(1) == StandingsCashSnapshot((20, 200.0), [new_status])
    finally:
        continue_writer.set()
        writer_thread.join(timeout=5)
        reader.close()
        writer.close()


def test_snapshot_read_guard_returns_none_on_sqlite_error(boom_conn):
    db = ContestDatabase.from_connection(boom_conn)
    assert db.get_standings_cash_snapshot(1) is None
    assert boom_conn.rolled_back is False


def test_snapshot_write_guard_rolls_back_on_sqlite_error(boom_conn):
    conn = boom_conn
    try:
        db = ContestDatabase.from_connection(conn)
        assert db.persist_standings_cash_snapshot(1, 1, 1.0, []) is None
        assert conn.rolled_back is True
    finally:
        conn.rollback()
