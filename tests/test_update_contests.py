import datetime
import sqlite3

import update_contests


def test_parse_start_date_handles_str_and_datetime():
    dt = datetime.datetime(2026, 1, 1, 0, 0, 0)
    assert update_contests._parse_start_date(dt) == dt
    assert update_contests._parse_start_date("2026-01-01 00:00:00") == dt
    assert update_contests._parse_start_date("bad-date") is None


def test_format_contest_announcement_adds_relative_time():
    now = datetime.datetime.now().replace(microsecond=0)
    start_date = now + datetime.timedelta(minutes=13, seconds=30)

    msg = update_contests._format_contest_announcement(
        "Contest starting soon",
        "NBA",
        "Test Contest",
        start_date.isoformat(sep=" "),
        123,
    )

    assert "(⏳ 13m)" in msg
    assert "Contest starting soon" in msg


def test_warning_notification_sent_for_upcoming_contest(monkeypatch):
    conn = sqlite3.connect(":memory:")
    conn.execute(
        """
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
    )
    update_contests.create_notifications_table(conn)

    class DummySport:
        name = "NBA"
        sheet_min_entry_fee = 25
        keyword = "%"

    monkeypatch.setattr(
        update_contests, "_sport_choices", lambda: {"nba": DummySport}
    )

    start_date = (datetime.datetime.now() + datetime.timedelta(minutes=10)).strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    later_start = (datetime.datetime.now() + datetime.timedelta(minutes=12)).strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    conn.execute(
        """
        INSERT INTO contests (
            dk_id, sport, name, start_date, draft_group, total_prizes, entries,
            positions_paid, entry_fee, entry_count, max_entry_count, completed, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (123, "NBA", "Test Contest", start_date, 1, 0, 0, None, 25, 0, 0, 0, None),
    )
    conn.execute(
        """
        INSERT INTO contests (
            dk_id, sport, name, start_date, draft_group, total_prizes, entries,
            positions_paid, entry_fee, entry_count, max_entry_count, completed, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (124, "NBA", "Later Contest", later_start, 2, 0, 0, None, 25, 0, 0, 0, None),
    )
    conn.commit()

    class FakeSender:
        def __init__(self):
            self.messages = []

        def send_message(self, message: str) -> None:
            self.messages.append(message)

    sender = FakeSender()
    monkeypatch.setattr(update_contests, "_build_discord_sender", lambda: sender)

    update_contests.check_contests_for_completion(conn)

    assert len(sender.messages) == 1
    assert "Contest starting soon" in sender.messages[0]
    assert "NBA" in sender.messages[0]
    assert "Test Contest" in sender.messages[0]
    assert update_contests.db_has_notification(conn, 123, "warning") is True
    assert update_contests.db_has_notification(conn, 124, "warning") is False
