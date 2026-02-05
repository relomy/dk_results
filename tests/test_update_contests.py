import datetime
import sqlite3

import yaml

import update_contests


def test_parse_start_date_handles_str_and_datetime():
    dt = datetime.datetime(2026, 1, 1, 0, 0, 0)
    assert update_contests._parse_start_date(dt) == dt
    assert update_contests._parse_start_date("2026-01-01 00:00:00") == dt
    assert update_contests._parse_start_date("bad-date") is None


def test_format_contest_announcement_adds_relative_time(monkeypatch):
    monkeypatch.setattr(update_contests, "SPREADSHEET_ID", "test-sheet")
    monkeypatch.setattr(update_contests, "SHEET_GID_MAP", {"NBA": 123})
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
    assert "🔗 DK: [123]" in msg
    assert "📊 Sheet: [NBA]" in msg

    print("\n---\n", msg, "\n---\n")


def test_load_warning_schedule_map_normalizes_and_logs(tmp_path, monkeypatch):
    schedule_path = tmp_path / "contest_warning_schedules.yaml"
    schedule_path.write_text(
        yaml.safe_dump(
            {
                "default": [25, "bad", -5, 25],
                "NBA": [60, 30, 30],
                "NFL": "oops",
            }
        )
    )
    monkeypatch.setenv("CONTEST_WARNING_SCHEDULE_FILE", str(schedule_path))

    captured = []
    monkeypatch.setattr(
        update_contests.logger,
        "warning",
        lambda message, *args: captured.append(message % args if args else message),
    )
    schedules = update_contests._load_warning_schedule_map()

    assert schedules["default"] == [25]
    assert schedules["nba"] == [30, 60]
    assert "nfl" not in schedules
    assert any("warning schedule" in message.lower() for message in captured)


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

    monkeypatch.setattr(update_contests, "_sport_choices", lambda: {"nba": DummySport})

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
    assert "Contest starting soon (25m)" in sender.messages[0]
    assert "NBA" in sender.messages[0]
    assert "Test Contest" in sender.messages[0]
    assert update_contests.db_has_notification(conn, 123, "warning:25") is True
    assert update_contests.db_has_notification(conn, 124, "warning:25") is False


def test_warning_notifications_sent_for_multiple_thresholds(monkeypatch):
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

    monkeypatch.setattr(update_contests, "_sport_choices", lambda: {"nba": DummySport})
    monkeypatch.setattr(update_contests, "_warning_schedule_for", lambda _sport: [25, 5])

    start_date = (datetime.datetime.now() + datetime.timedelta(minutes=3)).strftime(
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
    conn.commit()

    class FakeSender:
        def __init__(self):
            self.messages = []

        def send_message(self, message: str) -> None:
            self.messages.append(message)

    sender = FakeSender()
    monkeypatch.setattr(update_contests, "_build_discord_sender", lambda: sender)

    update_contests.check_contests_for_completion(conn)

    assert len(sender.messages) == 2
    assert any("(25m)" in message for message in sender.messages)
    assert any("(5m)" in message for message in sender.messages)
    assert update_contests.db_has_notification(conn, 123, "warning:25") is True
    assert update_contests.db_has_notification(conn, 123, "warning:5") is True
