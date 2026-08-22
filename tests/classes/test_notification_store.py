import sqlite3

import pytest
from classes.notification_store import NotificationStore


@pytest.fixture
def conn():
    connection = sqlite3.connect(":memory:")
    try:
        yield connection
    finally:
        connection.close()


@pytest.fixture
def store(conn):
    return NotificationStore(conn)


def test_creates_tables_on_init(conn):
    NotificationStore(conn)
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert {"contest_notifications", "contest_vip_presence"} <= tables


def test_second_store_on_same_conn_is_safe(conn):
    NotificationStore(conn)
    # Re-initialising must not raise (CREATE IF NOT EXISTS).
    NotificationStore(conn)


def test_record_notification_is_idempotent(store):
    assert store.has_notification(101, "warning:30") is False
    store.record_notification(101, "warning:30")
    assert store.has_notification(101, "warning:30") is True
    # Recording the same event again writes no second row.
    store.record_notification(101, "warning:30")
    count = store._conn.execute(
        "SELECT COUNT(*) FROM contest_notifications WHERE dk_id=? AND event=?",
        (101, "warning:30"),
    ).fetchone()[0]
    assert count == 1


def test_has_notification_is_scoped_by_dk_id_and_event(store):
    store.record_notification(101, "live")
    assert store.has_notification(101, "live") is True
    assert store.has_notification(101, "completed") is False
    assert store.has_notification(202, "live") is False


def test_has_any_soft_finish_notification(store):
    assert store.has_any_soft_finish_notification(101) is False
    store.record_notification(101, "warning:30")
    assert store.has_any_soft_finish_notification(101) is False
    store.record_notification(101, "soft_finish:abc")
    assert store.has_any_soft_finish_notification(101) is True
    # Scoped to the contest.
    assert store.has_any_soft_finish_notification(202) is False


def test_record_notification_swallows_sqlite_errors(store, caplog):
    store._conn.close()
    # Closed connection would raise; record_notification must log, not raise.
    store.record_notification(101, "live")
    assert "sqlite" in caplog.text.lower()


def test_presence_round_trips(store):
    assert store.get_presence(101) is None
    store.upsert_presence(101, "present")
    row = store.get_presence(101)
    assert row is not None
    status, checked_at = row
    assert status == "present"
    assert checked_at


def test_upsert_presence_overwrites_status(store):
    store.upsert_presence(101, "unknown")
    store.upsert_presence(101, "absent")
    status, _checked_at = store.get_presence(101)
    assert status == "absent"
    # Single row per contest.
    count = store._conn.execute("SELECT COUNT(*) FROM contest_vip_presence WHERE dk_id=?", (101,)).fetchone()[0]
    assert count == 1
