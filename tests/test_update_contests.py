import datetime
import runpy
import sqlite3
import sys

import pytest
import yaml

import dk_results.cli.update_contests as update_contests

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


def _create_contests_table(conn: sqlite3.Connection) -> None:
    conn.execute(CONTESTS_TABLE_SQL)
    conn.commit()


def _make_sender():
    class FakeSender:
        def __init__(self):
            self.messages = []

        def send_message(self, message: str) -> None:
            self.messages.append(message)

    return FakeSender()


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
    monkeypatch.setattr(update_contests, "WARNING_SCHEDULES", {"default": [25]})

    start_date = (datetime.datetime.now() + datetime.timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M:%S")
    later_start = (datetime.datetime.now() + datetime.timedelta(minutes=12)).strftime("%Y-%m-%d %H:%M:%S")
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
    monkeypatch.setattr(update_contests, "WARNING_SCHEDULES", {"default": [25, 5]})

    start_date = (datetime.datetime.now() + datetime.timedelta(minutes=3)).strftime("%Y-%m-%d %H:%M:%S")
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


def test_warning_logs_schedule_and_skip(monkeypatch):
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
    monkeypatch.setattr(update_contests, "_warning_schedule_for", lambda _sport: [25])
    monkeypatch.setattr(update_contests, "WARNING_SCHEDULES", {"default": [25], "nba": [25]})

    start_date = (datetime.datetime.now() + datetime.timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        """
        INSERT INTO contests (
            dk_id, sport, name, start_date, draft_group, total_prizes, entries,
            positions_paid, entry_fee, entry_count, max_entry_count, completed, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (123, "NBA", "Test Contest", start_date, 1, 0, 0, None, 25, 0, 0, 0, None),
    )
    update_contests.db_insert_notification(conn, 123, "warning:25")
    conn.commit()

    captured = []
    monkeypatch.setattr(
        update_contests.logger,
        "debug",
        lambda message, *args: captured.append(message % args if args else message),
    )

    class FakeSender:
        def __init__(self):
            self.messages = []

        def send_message(self, message: str) -> None:
            self.messages.append(message)

    sender = FakeSender()
    monkeypatch.setattr(update_contests, "_build_discord_sender", lambda: sender)

    update_contests.check_contests_for_completion(conn)

    assert any("warning schedule for NBA" in msg for msg in captured)
    assert any("warning already sent" in msg.lower() for msg in captured)


def test_is_notifications_enabled_false(monkeypatch):
    monkeypatch.setattr(update_contests, "DISCORD_NOTIFICATIONS_ENABLED", "false")
    assert update_contests._is_notifications_enabled() is False


def test_sport_choices_filters_invalid():
    class DummySport(update_contests.Sport):
        name = ""

    choices = update_contests._sport_choices()
    assert "" not in choices


def test_build_discord_sender_disabled(monkeypatch):
    monkeypatch.setattr(update_contests, "DISCORD_NOTIFICATIONS_ENABLED", "false")
    assert update_contests._build_discord_sender() is None


def test_build_discord_sender_missing_config(monkeypatch):
    monkeypatch.setattr(update_contests, "DISCORD_NOTIFICATIONS_ENABLED", "true")
    monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
    monkeypatch.delenv("DISCORD_CHANNEL_ID", raising=False)
    assert update_contests._build_discord_sender() is None


def test_build_discord_sender_invalid_channel(monkeypatch):
    monkeypatch.setattr(update_contests, "DISCORD_NOTIFICATIONS_ENABLED", "true")
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "tok")
    monkeypatch.setenv("DISCORD_CHANNEL_ID", "bad")
    assert update_contests._build_discord_sender() is None


def test_load_sheet_gid_map_missing_file(tmp_path, monkeypatch):
    monkeypatch.setattr(update_contests, "SHEET_GIDS_FILE", str(tmp_path / "missing.yaml"))
    assert update_contests._load_sheet_gid_map() == {}


def test_normalize_warning_schedule_non_list():
    assert update_contests._normalize_warning_schedule("bad", key="nba") == []


def test_warning_schedule_for_fallback(monkeypatch):
    monkeypatch.setattr(update_contests, "WARNING_SCHEDULES", {"default": [10]})
    assert update_contests._warning_schedule_for("NBA") == [10]


def test_sheet_link_missing(monkeypatch):
    monkeypatch.setattr(update_contests, "SPREADSHEET_ID", None)
    assert update_contests._sheet_link("NBA") is None


def test_sport_emoji_default():
    assert update_contests._sport_emoji("UNKNOWN") == "🏟️"


def test_format_contest_announcement_seconds_only(monkeypatch):
    class FixedDateTime(datetime.datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2024, 1, 1, 0, 0, 0, tzinfo=tz)

    monkeypatch.setattr(update_contests.datetime, "datetime", FixedDateTime)

    message = update_contests._format_contest_announcement(
        "Contest starting soon",
        "NBA",
        "Contest",
        "2024-01-01 00:00:05",
        123,
    )
    assert "(⏳ 5s)" in message


def test_create_and_has_notification():
    conn = sqlite3.connect(":memory:")
    update_contests.create_notifications_table(conn)
    update_contests.db_insert_notification(conn, 1, "live")
    assert update_contests.db_has_notification(conn, 1, "live") is True


def test_db_insert_notification_handles_error():
    class BoomConn:
        def cursor(self):
            raise sqlite3.Error("boom")

    update_contests.db_insert_notification(BoomConn(), 1, "live")


def test_check_contests_for_completion_live_and_completed(monkeypatch):
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

    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    insert_sql = (
        "INSERT INTO contests (dk_id, sport, name, start_date, draft_group, "
        "total_prizes, entries, positions_paid, entry_fee, entry_count, "
        "max_entry_count, completed, status) "
        "VALUES (?, 'NBA', ?, ?, ?, 0, 0, NULL, 25, 0, 1, 0, ?)"
    )
    conn.execute(
        insert_sql,
        (1, "Contest1", now, 10, "UPCOMING"),
    )
    conn.execute(
        insert_sql,
        (2, "Contest2", now, 11, "LIVE"),
    )
    conn.commit()

    update_contests.db_insert_notification(conn, 2, "live")

    class DummySport:
        name = "NBA"
        sheet_min_entry_fee = 25
        keyword = "%"

    class FakeSender:
        def __init__(self):
            self.messages = []

        def send_message(self, message: str) -> None:
            self.messages.append(message)

    sender = FakeSender()

    monkeypatch.setattr(update_contests, "_build_discord_sender", lambda: sender)
    monkeypatch.setattr(update_contests, "_warning_schedule_for", lambda _sport: [])
    monkeypatch.setattr(update_contests, "_sport_choices", lambda: {"NBA": DummySport})

    monkeypatch.setattr(
        update_contests,
        "db_get_live_contest",
        lambda *_a, **_k: (1, "Contest1", None, None, now),
    )

    def fake_get_contest_data(dk_id):
        if dk_id == 1:
            return {
                "completed": 0,
                "status": "LIVE",
                "entries": 0,
                "positions_paid": 10,
            }
        return {
            "completed": 1,
            "status": "COMPLETED",
            "entries": 0,
            "positions_paid": 10,
        }

    monkeypatch.setattr(update_contests, "get_contest_data", fake_get_contest_data)

    update_contests.check_contests_for_completion(conn)

    assert any("Contest started" in msg for msg in sender.messages)
    assert any("Contest ended" in msg for msg in sender.messages)


def test_get_contest_data_returns_none_on_bad_status(monkeypatch):
    class FakeDK:
        def get_contest_detail(self, dk_id):
            return {
                "contestDetail": {
                    "payoutSummary": [{"maxPosition": 1}],
                    "contestStateDetail": "POSTPONED",
                    "maximumEntries": 0,
                }
            }

    monkeypatch.setattr(update_contests, "Draftkings", FakeDK)

    assert update_contests.get_contest_data(1) is None


def test_db_update_contest_success():
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE contests (dk_id INTEGER PRIMARY KEY, positions_paid INTEGER, status TEXT, completed INTEGER)"
    )
    conn.execute("INSERT INTO contests (dk_id, positions_paid, status, completed) VALUES (1, NULL, 'LIVE', 0)")
    conn.commit()

    update_contests.db_update_contest(conn, [10, "COMPLETED", 1, 1])


def test_db_get_incomplete_contests_error(monkeypatch):
    class BoomConn:
        def cursor(self):
            raise sqlite3.Error("boom")

    assert update_contests.db_get_incomplete_contests(BoomConn()) is None


def test_db_get_next_upcoming_contest_error(monkeypatch):
    class BoomConn:
        def cursor(self):
            raise sqlite3.Error("boom")

    assert update_contests.db_get_next_upcoming_contest(BoomConn(), "NBA") is None


def test_db_get_next_upcoming_contest_any_error(monkeypatch):
    class BoomConn:
        def cursor(self):
            raise sqlite3.Error("boom")

    assert update_contests.db_get_next_upcoming_contest_any(BoomConn(), "NBA") is None


def test_main_handles_sqlite_error_without_state_dir(monkeypatch):
    def boom(_path):
        raise sqlite3.Error("boom")

    monkeypatch.setattr(update_contests.sqlite3, "connect", boom)
    monkeypatch.setenv("DFS_STATE_DIR", "/tmp")
    update_contests.main()


def test_main_uses_dfs_common_schema_init(monkeypatch):
    calls = {"db_path": 0, "init_schema": 0}

    def fake_db_path():
        calls["db_path"] += 1
        return "/tmp/contests.db"

    def fake_init_schema(path):
        calls["init_schema"] += 1
        assert path == "/tmp/contests.db"
        return path

    class FakeConn:
        pass

    monkeypatch.setattr(update_contests.state, "contests_db_path", fake_db_path)
    monkeypatch.setattr(update_contests.contests, "init_schema", fake_init_schema)
    monkeypatch.setattr(update_contests.sqlite3, "connect", lambda _p: FakeConn())
    monkeypatch.setattr(update_contests, "check_contests_for_completion", lambda _c: None)

    update_contests.main()

    assert calls == {"db_path": 2, "init_schema": 1}


def test_load_sheet_gid_map_valid_entries(tmp_path, monkeypatch):
    path = tmp_path / "gids.yaml"
    path.write_text("NBA: 10\nbad: x\n42: 3\n")
    monkeypatch.setattr(update_contests, "SHEET_GIDS_FILE", str(path))

    assert update_contests._load_sheet_gid_map() == {"NBA": 10}


def test_load_warning_schedule_map_missing_file(tmp_path, monkeypatch):
    missing = tmp_path / "missing.yaml"
    monkeypatch.setenv(update_contests.WARNING_SCHEDULE_FILE_ENV, str(missing))

    result = update_contests._load_warning_schedule_map()

    assert result == {"default": update_contests._DEFAULT_WARNING_SCHEDULE}


def test_load_warning_schedule_map_invalid_yaml(tmp_path, monkeypatch):
    path = tmp_path / "bad.yaml"
    path.write_text("bad: yaml: :")
    monkeypatch.setenv(update_contests.WARNING_SCHEDULE_FILE_ENV, str(path))

    def boom(_text):
        raise RuntimeError("boom")

    monkeypatch.setattr(update_contests.yaml, "safe_load", boom)

    result = update_contests._load_warning_schedule_map()

    assert result == {"default": update_contests._DEFAULT_WARNING_SCHEDULE}


def test_load_warning_schedule_map_invalid_keys_and_default(tmp_path, monkeypatch):
    path = tmp_path / "sched.yaml"
    path.write_text('"": [5]\n1: [10]\nNBA: [10, -1, "bad"]\n')
    monkeypatch.setenv(update_contests.WARNING_SCHEDULE_FILE_ENV, str(path))

    result = update_contests._load_warning_schedule_map()

    assert result["nba"] == [10]
    assert "default" in result


def test_format_contest_announcement_days_hours(monkeypatch):
    class FixedDateTime(datetime.datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2024, 1, 1, 0, 0, 0, tzinfo=tz)

    monkeypatch.setattr(update_contests.datetime, "datetime", FixedDateTime)

    message = update_contests._format_contest_announcement(
        "Contest starting soon",
        "NBA",
        "Contest",
        "2024-01-02 02:00:00",
        123,
    )

    assert "(⏳ 1d2h)" in message


def test_parse_start_date_with_datetime():
    dt = datetime.datetime(2024, 1, 1, 0, 0, 0)
    assert update_contests._parse_start_date(dt) is dt


def test_check_contests_for_completion_sends_warning(monkeypatch):
    conn = sqlite3.connect(":memory:")

    class DummySport:
        name = "NBA"
        sheet_min_entry_fee = 25
        keyword = "%"

    class FakeSender:
        def __init__(self):
            self.messages = []

        def send_message(self, message: str):
            self.messages.append(message)

    sender = FakeSender()

    monkeypatch.setattr(update_contests, "_build_discord_sender", lambda: sender)
    monkeypatch.setattr(update_contests, "_sport_choices", lambda: {"NBA": DummySport})
    monkeypatch.setattr(update_contests, "_warning_schedule_for", lambda _sport: [10])
    monkeypatch.setattr(update_contests, "db_has_notification", lambda *_a, **_k: False)
    monkeypatch.setattr(update_contests, "db_get_incomplete_contests", lambda _conn: [])

    class FixedDateTime(datetime.datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2024, 1, 1, 0, 0, 0, tzinfo=tz)

    monkeypatch.setattr(update_contests.datetime, "datetime", FixedDateTime)

    start_date = "2024-01-01 00:05:00"
    monkeypatch.setattr(
        update_contests,
        "db_get_next_upcoming_contest",
        lambda *_a, **_k: (1, "Contest", None, None, start_date),
    )
    monkeypatch.setattr(
        update_contests,
        "db_get_next_upcoming_contest_any",
        lambda *_a, **_k: None,
    )

    update_contests.check_contests_for_completion(conn)

    assert sender.messages


def test_check_contests_for_completion_skip_branches(monkeypatch):
    conn = sqlite3.connect(":memory:")

    monkeypatch.setattr(update_contests, "db_get_live_contest", lambda *_a, **_k: None)
    monkeypatch.setattr(update_contests, "_build_discord_sender", lambda: None)
    monkeypatch.setattr(update_contests, "_sport_choices", lambda: {})

    rows = [
        (1, 10, 0, 5, "LIVE", 0, "Contest1", "2024-01-01 00:00:00", "NBA"),
        (2, 10, 0, 5, "LIVE", 0, "Contest2", "2024-01-01 00:00:00", "NBA"),
        (3, 20, 0, None, "LIVE", 0, "Contest3", "2024-01-01 00:00:00", "NBA"),
    ]
    monkeypatch.setattr(update_contests, "db_get_incomplete_contests", lambda _c: rows)

    def fake_get_contest_data(dk_id):
        if dk_id == 1:
            return {
                "positions_paid": 5,
                "status": "LIVE",
                "completed": 0,
                "entries": 0,
            }
        return None

    monkeypatch.setattr(update_contests, "get_contest_data", fake_get_contest_data)

    update_contests.check_contests_for_completion(conn)


def test_check_contests_for_completion_notification_branches(monkeypatch):
    conn = sqlite3.connect(":memory:")

    class DummySport:
        name = "NBA"
        sheet_min_entry_fee = 25
        keyword = "%"

    class FakeSender:
        def __init__(self):
            self.messages = []

        def send_message(self, message: str):
            self.messages.append(message)

    sender = FakeSender()

    monkeypatch.setattr(
        update_contests,
        "db_get_live_contest",
        lambda *_a, **_k: (1, "Contest", None, None, "2024-01-01 00:00:00"),
    )
    monkeypatch.setattr(update_contests, "_build_discord_sender", lambda: sender)
    monkeypatch.setattr(update_contests, "_sport_choices", lambda: {"NBA": DummySport})
    monkeypatch.setattr(update_contests, "db_get_next_upcoming_contest", lambda *_a, **_k: None)
    monkeypatch.setattr(update_contests, "db_get_next_upcoming_contest_any", lambda *_a, **_k: None)

    rows = [
        (1, 10, 0, None, "UPCOMING", 0, "Contest1", "2024-01-01 00:00:00", "NBA"),
        (2, 11, 0, None, "LIVE", 0, "Contest2", "2024-01-01 00:00:00", "NBA"),
        (3, 12, 0, None, "LIVE", 0, "Contest3", "2024-01-01 00:00:00", "NBA"),
    ]
    monkeypatch.setattr(update_contests, "db_get_incomplete_contests", lambda _c: rows)

    def fake_get_contest_data(dk_id):
        if dk_id == 1:
            return {"positions_paid": 0, "status": "LIVE", "completed": 0, "entries": 0}
        return {
            "positions_paid": 0,
            "status": "COMPLETED",
            "completed": 1,
            "entries": 0,
        }

    monkeypatch.setattr(update_contests, "get_contest_data", fake_get_contest_data)

    def fake_has_notification(_conn, dk_id, event):
        if dk_id == 1 and event == "live":
            return True
        if dk_id == 2 and event == "completed":
            return True
        return False

    monkeypatch.setattr(update_contests, "db_has_notification", fake_has_notification)

    update_contests.check_contests_for_completion(conn)


def test_get_contest_data_success(monkeypatch):
    class FakeDK:
        def get_contest_detail(self, dk_id):
            return {
                "contestDetail": {
                    "payoutSummary": [{"maxPosition": 5}],
                    "contestStateDetail": "live",
                    "maximumEntries": 100,
                }
            }

    monkeypatch.setattr(update_contests, "Draftkings", FakeDK)

    data = update_contests.get_contest_data(1)

    assert data == {
        "completed": 0,
        "status": "LIVE",
        "entries": 100,
        "positions_paid": 5,
    }


def test_get_contest_data_request_error(monkeypatch):
    class FakeDK:
        def get_contest_detail(self, dk_id):
            raise Exception("boom")

    monkeypatch.setattr(update_contests, "Draftkings", FakeDK)

    assert update_contests.get_contest_data(1) is None


def test_get_contest_data_value_error(monkeypatch):
    class FakeDK:
        def get_contest_detail(self, dk_id):
            raise ValueError("bad json")

    monkeypatch.setattr(update_contests, "Draftkings", FakeDK)

    assert update_contests.get_contest_data(1) is None


def test_get_contest_data_key_error(monkeypatch):
    class FakeDK:
        def get_contest_detail(self, dk_id):
            return {}

    monkeypatch.setattr(update_contests, "Draftkings", FakeDK)

    assert update_contests.get_contest_data(1) is None


def test_db_update_contest_handles_error():
    class BoomCursor:
        def execute(self, *_a, **_k):
            raise sqlite3.Error("boom")

    class BoomConn:
        def cursor(self):
            return BoomCursor()

        def commit(self):
            return None

    update_contests.db_update_contest(BoomConn(), [1, "LIVE", 0, 1])


def test_main_handles_sqlite_error(monkeypatch):
    def boom(_path):
        raise sqlite3.Error("boom")

    monkeypatch.setattr(update_contests.sqlite3, "connect", boom)
    update_contests.main()


def test_main_handles_unexpected_error(monkeypatch):
    def boom(_path):
        raise RuntimeError("boom")

    monkeypatch.setattr(update_contests.sqlite3, "connect", boom)
    update_contests.main()


def test_module_main_executes(monkeypatch):
    def boom(_path):
        raise sqlite3.Error("boom")

    monkeypatch.setattr("sqlite3.connect", boom)
    existing = sys.modules.pop("dk_results.cli.update_contests", None)
    try:
        runpy.run_module("dk_results.cli.update_contests", run_name="__main__")
    finally:
        if existing is not None:
            sys.modules["dk_results.cli.update_contests"] = existing


def test_build_discord_sender_success_path(monkeypatch):
    monkeypatch.setattr(update_contests, "DISCORD_NOTIFICATIONS_ENABLED", "true")
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "tok")
    monkeypatch.setenv("DISCORD_CHANNEL_ID", "123")

    sender = update_contests._build_discord_sender()

    assert isinstance(sender, update_contests.DiscordRest)
    assert sender.token == "tok"
    assert sender.channel_id == 123


def test_load_sheet_gid_map_unset(monkeypatch):
    monkeypatch.setattr(update_contests, "SHEET_GIDS_FILE", "")
    assert update_contests._load_sheet_gid_map() == {}


def test_load_sheet_gid_map_safe_load_error(tmp_path, monkeypatch):
    path = tmp_path / "gids.yaml"
    path.write_text("NBA: 10\n")
    monkeypatch.setattr(update_contests, "SHEET_GIDS_FILE", str(path))

    def boom(_text):
        raise RuntimeError("boom")

    monkeypatch.setattr(update_contests.yaml, "safe_load", boom)

    assert update_contests._load_sheet_gid_map() == {}


def test_load_sheet_gid_map_non_dict(tmp_path, monkeypatch):
    path = tmp_path / "gids.yaml"
    path.write_text("- 1\n")
    monkeypatch.setattr(update_contests, "SHEET_GIDS_FILE", str(path))
    monkeypatch.setattr(update_contests.yaml, "safe_load", lambda _text: ["bad"])

    assert update_contests._load_sheet_gid_map() == {}


def test_load_warning_schedule_map_non_dict(tmp_path, monkeypatch):
    path = tmp_path / "sched.yaml"
    path.write_text("- 1\n")
    monkeypatch.setenv(update_contests.WARNING_SCHEDULE_FILE_ENV, str(path))
    monkeypatch.setattr(update_contests.yaml, "safe_load", lambda _text: ["bad"])

    result = update_contests._load_warning_schedule_map()

    assert result == {"default": update_contests._DEFAULT_WARNING_SCHEDULE}


def test_parse_start_date_datetime():
    dt = datetime.datetime(2024, 1, 1, 0, 0, 0)
    assert update_contests._parse_start_date(dt) is dt


def test_parse_start_date_empty_returns_none():
    assert update_contests._parse_start_date(None) is None


def test_check_contests_for_completion_warning_path(monkeypatch):
    conn = sqlite3.connect(":memory:")

    class DummySport:
        name = "NBA"
        sheet_min_entry_fee = 25
        keyword = "%"

    class FakeSender:
        def __init__(self):
            self.messages = []

        def send_message(self, message: str):
            self.messages.append(message)

    sender = FakeSender()

    start_date = (datetime.datetime.now() + datetime.timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")

    monkeypatch.setattr(update_contests, "_build_discord_sender", lambda: sender)
    monkeypatch.setattr(update_contests, "_sport_choices", lambda: {"NBA": DummySport})
    monkeypatch.setattr(update_contests, "_warning_schedule_for", lambda _sport: [10])
    monkeypatch.setattr(update_contests, "db_has_notification", lambda *_a, **_k: False)
    monkeypatch.setattr(update_contests, "db_get_incomplete_contests", lambda _c: [])
    monkeypatch.setattr(
        update_contests,
        "db_get_next_upcoming_contest",
        lambda *_a, **_k: (1, "Contest", None, None, start_date),
    )
    monkeypatch.setattr(
        update_contests,
        "db_get_next_upcoming_contest_any",
        lambda *_a, **_k: None,
    )

    update_contests.check_contests_for_completion(conn)

    assert sender.messages


def test_check_contests_for_completion_skips_missing_start_dt(monkeypatch):
    conn = sqlite3.connect(":memory:")

    class DummySport:
        name = "NBA"
        sheet_min_entry_fee = 25
        keyword = "%"

    class FakeSender:
        def __init__(self):
            self.messages = []

        def send_message(self, message: str):
            self.messages.append(message)

    sender = FakeSender()

    monkeypatch.setattr(update_contests, "_build_discord_sender", lambda: sender)
    monkeypatch.setattr(update_contests, "_sport_choices", lambda: {"NBA": DummySport})
    monkeypatch.setattr(update_contests, "db_get_incomplete_contests", lambda _c: [])
    monkeypatch.setattr(
        update_contests,
        "db_get_next_upcoming_contest",
        lambda *_a, **_k: (1, "Contest", None, None, None),
    )
    monkeypatch.setattr(update_contests, "db_get_next_upcoming_contest_any", lambda *_a, **_k: None)

    update_contests.check_contests_for_completion(conn)

    assert sender.messages == []


def test_check_contests_for_completion_warning_outside_window(monkeypatch):
    conn = sqlite3.connect(":memory:")

    class DummySport:
        name = "NBA"
        sheet_min_entry_fee = 25
        keyword = "%"

    class FakeSender:
        def __init__(self):
            self.messages = []

        def send_message(self, message: str):
            self.messages.append(message)

    sender = FakeSender()

    start_date = (datetime.datetime.now() + datetime.timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S")

    monkeypatch.setattr(update_contests, "_build_discord_sender", lambda: sender)
    monkeypatch.setattr(update_contests, "_sport_choices", lambda: {"NBA": DummySport})
    monkeypatch.setattr(update_contests, "_warning_schedule_for", lambda _sport: [5])
    monkeypatch.setattr(update_contests, "db_has_notification", lambda *_a, **_k: False)
    monkeypatch.setattr(update_contests, "db_get_incomplete_contests", lambda _c: [])
    monkeypatch.setattr(
        update_contests,
        "db_get_next_upcoming_contest",
        lambda *_a, **_k: (1, "Contest", None, None, start_date),
    )
    monkeypatch.setattr(update_contests, "db_get_next_upcoming_contest_any", lambda *_a, **_k: None)

    update_contests.check_contests_for_completion(conn)

    assert sender.messages == []


def test_check_contests_for_completion_logs_exception(monkeypatch):
    conn = sqlite3.connect(":memory:")

    monkeypatch.setattr(update_contests, "db_get_live_contest", lambda *_a, **_k: None)
    monkeypatch.setattr(update_contests, "_build_discord_sender", lambda: None)
    monkeypatch.setattr(update_contests, "_sport_choices", lambda: {})
    monkeypatch.setattr(
        update_contests,
        "db_get_incomplete_contests",
        lambda _c: [(1, 10, 0, None, "LIVE", 0, "Contest", "2024-01-01 00:00:00", "NBA")],
    )

    def boom(_dk_id):
        raise RuntimeError("boom")

    monkeypatch.setattr(update_contests, "get_contest_data", boom)

    update_contests.check_contests_for_completion(conn)


def test_main_happy_path(monkeypatch):
    called = {}

    class FakeConn:
        pass

    monkeypatch.setattr(update_contests.sqlite3, "connect", lambda _p: FakeConn())
    monkeypatch.setattr(
        update_contests,
        "check_contests_for_completion",
        lambda c: called.setdefault("ok", True),
    )
    monkeypatch.setenv("DFS_STATE_DIR", "/tmp")
    monkeypatch.setattr(update_contests.state, "contests_db_path", lambda: "/tmp/contests.db")
    monkeypatch.setattr(update_contests.contests, "init_schema", lambda _p: None)

    update_contests.main()

    assert called["ok"] is True


def test_main_help_exits_without_runtime(monkeypatch):
    def boom(_path):
        raise AssertionError("sqlite connect should not run for --help")

    monkeypatch.setattr(update_contests.sqlite3, "connect", boom)

    with pytest.raises(SystemExit) as exc:
        update_contests.main(["--help"])

    assert exc.value.code == 0


def _soft_finish_conn() -> sqlite3.Connection:
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
    return conn


def _insert_live_contest_row(conn: sqlite3.Connection, *, dk_id: int = 1001, draft_group: int = 77) -> None:
    conn.execute(
        """
        INSERT INTO contests (
            dk_id, sport, name, start_date, draft_group, total_prizes, entries,
            positions_paid, entry_fee, entry_count, max_entry_count, completed, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            dk_id,
            "NBA",
            "Primary Live Contest",
            "2024-01-01 00:00:00",
            draft_group,
            0,
            5000,
            100,
            25,
            5000,
            5000,
            0,
            "LIVE",
        ),
    )
    conn.commit()


def _make_leaderboard_payload(
    *,
    top_score=229,
    cashing_score=185.5,
    leader_time=0,
    last_winning_time=0,
    rows: list[dict] | None = None,
) -> dict:
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
        "leader": {"timeRemaining": leader_time, "fantasyPoints": top_score},
        "lastWinningEntry": {"timeRemaining": last_winning_time, "fantasyPoints": cashing_score},
        "leaderBoard": rows,
    }


def _configure_soft_finish_test_env(
    monkeypatch,
    tmp_path,
    *,
    payloads: list[dict],
    get_contest_data_fn=None,
    live_dk_id: int = 1001,
):
    class DummySport:
        name = "NBA"
        sheet_min_entry_fee = 25
        keyword = "%"

    class FakeSender:
        def __init__(self):
            self.messages = []

        def send_message(self, message: str):
            self.messages.append(message)

    sender = FakeSender()
    monkeypatch.setattr(update_contests, "_build_discord_sender", lambda: sender)
    monkeypatch.setattr(update_contests, "_sport_choices", lambda: {"NBA": DummySport})
    monkeypatch.setattr(update_contests, "_warning_schedule_for", lambda _sport: [])
    monkeypatch.setattr(update_contests, "db_get_next_upcoming_contest", lambda *_a, **_k: None)
    monkeypatch.setattr(update_contests, "db_get_next_upcoming_contest_any", lambda *_a, **_k: None)
    monkeypatch.setattr(
        update_contests,
        "db_get_live_contest",
        lambda *_a, **_k: (live_dk_id, "Primary Live Contest", 77, 100, "2024-01-01 00:00:00"),
    )
    if get_contest_data_fn is None:

        def default_get_contest_data(_dk_id):
            return {"positions_paid": 100, "status": "LIVE", "completed": 0, "entries": 5000}

        get_contest_data_fn = default_get_contest_data
    monkeypatch.setattr(update_contests, "get_contest_data", get_contest_data_fn)

    payload_iter = iter(payloads)

    class FakeDK:
        def __init__(self):
            pass

        def get_leaderboard(self, _dk_id, timeout=None, session=None):
            try:
                return next(payload_iter)
            except StopIteration:
                return payloads[-1]

    monkeypatch.setattr(update_contests, "Draftkings", FakeDK)

    vip_file = tmp_path / "vips.yaml"
    vip_file.write_text("- foobar\n- MissingVip\n")
    monkeypatch.setattr(update_contests, "repo_file", lambda *_parts: vip_file)
    return sender


def test_soft_finish_sends_summary_once(monkeypatch, tmp_path):
    conn = _soft_finish_conn()
    _insert_live_contest_row(conn)
    sender = _configure_soft_finish_test_env(
        monkeypatch,
        tmp_path,
        payloads=[_make_leaderboard_payload()],
    )

    update_contests.check_contests_for_completion(conn)

    assert len(sender.messages) == 1
    assert any("Contest soft-finished" in message for message in sender.messages)
    assert any("Top score" in message for message in sender.messages)
    assert any("Cashing score" in message for message in sender.messages)


def test_soft_finish_does_not_resend_for_same_summary(monkeypatch, tmp_path):
    conn = _soft_finish_conn()
    _insert_live_contest_row(conn)
    payload = _make_leaderboard_payload(top_score=221.5, cashing_score=180.25)
    sender = _configure_soft_finish_test_env(monkeypatch, tmp_path, payloads=[payload, payload])

    update_contests.check_contests_for_completion(conn)
    update_contests.check_contests_for_completion(conn)

    assert len(sender.messages) == 1


def test_soft_finish_resends_when_summary_changes(monkeypatch, tmp_path):
    conn = _soft_finish_conn()
    _insert_live_contest_row(conn)
    payload_a = _make_leaderboard_payload(top_score=221.5, cashing_score=180.25)
    payload_b = _make_leaderboard_payload(top_score=223.0, cashing_score=181.0)
    sender = _configure_soft_finish_test_env(monkeypatch, tmp_path, payloads=[payload_a, payload_b])

    update_contests.check_contests_for_completion(conn)
    update_contests.check_contests_for_completion(conn)

    assert len(sender.messages) == 2


def test_soft_finish_vip_matching_is_case_insensitive_visible_rows_only(monkeypatch, tmp_path):
    conn = _soft_finish_conn()
    _insert_live_contest_row(conn)
    payload = _make_leaderboard_payload(
        rows=[
            {
                "userName": "FooBar",
                "timeRemaining": 0,
                "fantasyPoints": 220,
                "winningValue": 150,
                "winnings": [{"value": 150, "description": "Cash"}],
            },
            {
                "userName": "NonVip",
                "timeRemaining": 0,
                "fantasyPoints": 210,
                "winningValue": 100,
                "winnings": [{"value": 100, "description": "Cash"}],
            },
        ]
    )
    sender = _configure_soft_finish_test_env(monkeypatch, tmp_path, payloads=[payload])

    update_contests.check_contests_for_completion(conn)

    msg = sender.messages[0]
    assert "FooBar" in msg
    assert "MissingVip" not in msg


def test_soft_finish_equivalent_numeric_payloads_do_not_duplicate_end_to_end(monkeypatch, tmp_path):
    conn = _soft_finish_conn()
    _insert_live_contest_row(conn)
    payload_ints = _make_leaderboard_payload(top_score=123, cashing_score=99)
    payload_decimals = _make_leaderboard_payload(top_score=123.00, cashing_score=99.0)
    sender = _configure_soft_finish_test_env(monkeypatch, tmp_path, payloads=[payload_ints, payload_decimals])

    update_contests.check_contests_for_completion(conn)
    update_contests.check_contests_for_completion(conn)

    assert len(sender.messages) == 1


def test_soft_finish_vip_case_variant_payloads_do_not_duplicate(monkeypatch, tmp_path):
    conn = _soft_finish_conn()
    _insert_live_contest_row(conn)
    payload_a = _make_leaderboard_payload(
        rows=[
            {
                "userName": "FooBar",
                "timeRemaining": 0,
                "fantasyPoints": 220,
                "winningValue": 100,
                "winnings": [{"value": 100, "description": "Cash"}],
            }
        ]
    )
    payload_b = _make_leaderboard_payload(
        rows=[
            {
                "userName": "foobar",
                "timeRemaining": 0,
                "fantasyPoints": 220,
                "winningValue": 100,
                "winnings": [{"value": 100, "description": "Cash"}],
            }
        ]
    )
    sender = _configure_soft_finish_test_env(monkeypatch, tmp_path, payloads=[payload_a, payload_b])

    update_contests.check_contests_for_completion(conn)
    update_contests.check_contests_for_completion(conn)

    assert len(sender.messages) == 1


def test_soft_finish_missing_or_non_numeric_time_remaining_blocks_send(monkeypatch, tmp_path):
    conn = _soft_finish_conn()
    _insert_live_contest_row(conn)
    payload_valid = _make_leaderboard_payload(top_score=220.5, cashing_score=180.0)
    payload_bad_time_remaining = _make_leaderboard_payload(
        top_score=221.5,
        cashing_score=181.0,
        rows=[
            {
                "userName": "FooBar",
                "timeRemaining": "N/A",
                "fantasyPoints": 221.5,
                "winningValue": 100,
                "winnings": [{"value": 100, "description": "Cash"}],
            }
        ],
    )
    payload_missing_time_remaining = _make_leaderboard_payload(
        top_score=223.0,
        cashing_score=182.0,
        rows=[
            {
                "userName": "FooBar",
                "fantasyPoints": 223.0,
                "winningValue": 100,
                "winnings": [{"value": 100, "description": "Cash"}],
            }
        ],
    )
    payload_none_time_remaining = _make_leaderboard_payload(
        top_score=224.0,
        cashing_score=183.0,
        rows=[
            {
                "userName": "FooBar",
                "timeRemaining": None,
                "fantasyPoints": 224.0,
                "winningValue": 100,
                "winnings": [{"value": 100, "description": "Cash"}],
            }
        ],
    )
    sender = _configure_soft_finish_test_env(
        monkeypatch,
        tmp_path,
        payloads=[
            payload_valid,
            payload_bad_time_remaining,
            payload_missing_time_remaining,
            payload_none_time_remaining,
        ],
    )

    update_contests.check_contests_for_completion(conn)
    update_contests.check_contests_for_completion(conn)
    update_contests.check_contests_for_completion(conn)
    update_contests.check_contests_for_completion(conn)

    assert len(sender.messages) == 1


def test_soft_finish_missing_contest_state_fields_skips_safely(monkeypatch, tmp_path):
    conn = _soft_finish_conn()
    _insert_live_contest_row(conn, dk_id=1001)
    payload_a = _make_leaderboard_payload(top_score=220.5, cashing_score=180.0)
    payload_b = _make_leaderboard_payload(top_score=222.0, cashing_score=181.5)

    live_state = {"value": {"positions_paid": 100, "status": "LIVE", "completed": 0, "entries": 5000}}

    def fake_get_contest_data(dk_id):
        if dk_id == 1001:
            return {"positions_paid": 100, "status": "LIVE", "completed": 0, "entries": 5000}
        if dk_id == 2002:
            return live_state["value"]
        return {"positions_paid": 100, "status": "LIVE", "completed": 0, "entries": 5000}

    sender = _configure_soft_finish_test_env(
        monkeypatch,
        tmp_path,
        payloads=[payload_a, payload_b, payload_b],
        get_contest_data_fn=fake_get_contest_data,
        live_dk_id=2002,
    )

    update_contests.check_contests_for_completion(conn)
    live_state["value"] = {"positions_paid": 100, "status": "LIVE"}  # missing completed
    update_contests.check_contests_for_completion(conn)
    live_state["value"] = {"positions_paid": 100, "completed": 0}  # missing status
    update_contests.check_contests_for_completion(conn)

    assert len(sender.messages) == 1


def test_soft_finish_non_int_completed_values_skip_safely(monkeypatch, tmp_path):
    conn = _soft_finish_conn()
    _insert_live_contest_row(conn, dk_id=1001)
    payload = _make_leaderboard_payload(top_score=220.5, cashing_score=180.0)

    live_state = {"value": {"positions_paid": 100, "status": "LIVE", "completed": 0, "entries": 5000}}

    def fake_get_contest_data(dk_id):
        if dk_id == 1001:
            return {"positions_paid": 100, "status": "LIVE", "completed": 0, "entries": 5000}
        if dk_id == 2002:
            return live_state["value"]
        return {"positions_paid": 100, "status": "LIVE", "completed": 0, "entries": 5000}

    sender = _configure_soft_finish_test_env(
        monkeypatch,
        tmp_path,
        payloads=[payload, payload, payload],
        get_contest_data_fn=fake_get_contest_data,
        live_dk_id=2002,
    )

    update_contests.check_contests_for_completion(conn)
    live_state["value"] = {"positions_paid": 100, "status": "LIVE", "completed": "0"}  # wrong type
    update_contests.check_contests_for_completion(conn)
    live_state["value"] = {"positions_paid": 100, "status": "LIVE", "completed": False}  # wrong type
    update_contests.check_contests_for_completion(conn)

    assert len(sender.messages) == 1


def test_soft_finish_runs_despite_skip_draft_groups_short_circuit(monkeypatch, tmp_path):
    conn = _soft_finish_conn()
    _insert_live_contest_row(conn, dk_id=1001, draft_group=77)
    _insert_live_contest_row(conn, dk_id=1002, draft_group=77)
    payload = _make_leaderboard_payload(top_score=220.5, cashing_score=180.0)

    def fake_get_contest_data(_dk_id):
        return {"positions_paid": 100, "status": "LIVE", "completed": 0, "entries": 5000}

    sender = _configure_soft_finish_test_env(
        monkeypatch,
        tmp_path,
        payloads=[payload],
        get_contest_data_fn=fake_get_contest_data,
        live_dk_id=1002,
    )

    update_contests.check_contests_for_completion(conn)

    assert len(sender.messages) == 1


def test_vip_presence_resolver_uses_draftkings_entrant_page_fetch():
    conn = sqlite3.connect(":memory:")
    update_contests.create_vip_presence_table(conn)
    calls: list[tuple[int, int]] = []

    class FakeDK:
        def get_contest_entrants_page(self, contest_id: int, page_no: int, timeout=None, session=None):
            calls.append((contest_id, page_no))
            if page_no == 1:
                return "<tr><td data-un='vipone'></td></tr>"
            return ""

    status = update_contests._resolve_vip_presence(
        conn,
        dk=FakeDK(),
        dk_id=123,
        start_date="2026-03-29 13:35:00",
        vip_names=["VipOne"],
    )

    assert status == update_contests.VIP_PRESENT
    assert calls == [(123, 1)]
    assert update_contests.db_get_vip_presence(conn, 123)[0] == update_contests.VIP_PRESENT


def test_resolve_vip_presence_marks_absent_when_all_pages_scanned():
    conn = sqlite3.connect(":memory:")
    update_contests.create_vip_presence_table(conn)

    class FakeDK:
        def get_contest_entrants_page(self, contest_id: int, page_no: int, timeout=None, session=None):
            if page_no == 1:
                return "<tr><td data-un='user1'></td><td data-un='user2'></td></tr>"
            return ""

    status = update_contests._resolve_vip_presence(
        conn,
        dk=FakeDK(),
        dk_id=202,
        start_date="2026-03-29 13:35:00",
        vip_names=["vip_alpha", "vip_beta"],
    )

    assert status == update_contests.VIP_ABSENT
    assert update_contests.db_get_vip_presence(conn, 202)[0] == update_contests.VIP_ABSENT


def test_resolve_vip_presence_returns_unknown_on_fetch_error():
    conn = sqlite3.connect(":memory:")
    update_contests.create_vip_presence_table(conn)

    class FakeDK:
        def get_contest_entrants_page(self, contest_id: int, page_no: int, timeout=None, session=None):
            raise RuntimeError("network down")

    status = update_contests._resolve_vip_presence(
        conn,
        dk=FakeDK(),
        dk_id=303,
        start_date="2026-03-29 13:35:00",
        vip_names=["vip_alpha"],
    )

    assert status == update_contests.VIP_UNKNOWN
    assert update_contests.db_get_vip_presence(conn, 303) is None


def test_resolve_vip_presence_returns_unknown_when_page_cap_hit(monkeypatch):
    conn = sqlite3.connect(":memory:")
    update_contests.create_vip_presence_table(conn)
    monkeypatch.setattr(update_contests, "VIP_ENTRANT_PAGE_LIMIT", 2)
    calls: list[int] = []

    class FakeDK:
        def get_contest_entrants_page(self, contest_id: int, page_no: int, timeout=None, session=None):
            calls.append(page_no)
            return "<tr><td data-un='user1'></td></tr>"

    status = update_contests._resolve_vip_presence(
        conn,
        dk=FakeDK(),
        dk_id=404,
        start_date="2026-03-29 13:35:00",
        vip_names=["vip_alpha"],
    )

    assert status == update_contests.VIP_UNKNOWN
    assert calls == [1, 2]
    assert update_contests.db_get_vip_presence(conn, 404) is None


def test_parse_entrant_usernames_accepts_single_or_double_quotes():
    html = "<td data-un='vip_alpha'></td><td data-un=\"vip_beta\"></td>"
    names = update_contests._parse_entrant_usernames(html)
    assert names == ["vip_alpha", "vip_beta"]


def test_should_refresh_absent_normalizes_timezone_before_subtraction():
    now_local = datetime.datetime.now().astimezone().replace(microsecond=0)
    checked_at = (now_local - datetime.timedelta(minutes=11)).replace(tzinfo=None).isoformat(sep=" ")
    start_date = (now_local + datetime.timedelta(minutes=30)).astimezone(datetime.timezone.utc).isoformat()

    assert update_contests._should_refresh_absent(checked_at, start_date) is True


def test_should_refresh_absent_is_sticky_after_start():
    now_local = datetime.datetime.now().replace(microsecond=0)
    checked_at = (now_local - datetime.timedelta(minutes=30)).isoformat(sep=" ")
    start_date = (now_local - datetime.timedelta(minutes=1)).isoformat(sep=" ")

    assert update_contests._should_refresh_absent(checked_at, start_date) is False


def test_warning_notification_suppressed_when_vip_presence_absent(monkeypatch):
    conn = sqlite3.connect(":memory:")
    _create_contests_table(conn)
    update_contests.create_notifications_table(conn)
    update_contests.create_vip_presence_table(conn)
    start_date = (datetime.datetime.now() + datetime.timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M:%S")
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

    class DummySport:
        name = "NBA"
        sheet_min_entry_fee = 25
        keyword = "%"

    resolver_calls: list[int] = []

    def fake_resolver(conn, *, dk, dk_id, start_date, vip_names):
        resolver_calls.append(dk_id)
        return update_contests.VIP_ABSENT

    sender = _make_sender()
    monkeypatch.setattr(update_contests, "_build_discord_sender", lambda: sender)
    monkeypatch.setattr(update_contests, "_sport_choices", lambda: {"nba": DummySport})
    monkeypatch.setattr(update_contests, "_warning_schedule_for", lambda _sport: [25])
    monkeypatch.setattr(update_contests, "_resolve_vip_presence", fake_resolver)
    monkeypatch.setattr(update_contests, "_maybe_send_soft_finish_announcement", lambda *args, **kwargs: None)

    update_contests.check_contests_for_completion(conn)

    assert resolver_calls == [123]
    assert sender.messages == []
    assert update_contests.db_has_notification(conn, 123, "warning:25") is False


def test_warning_notification_sent_when_vip_presence_unknown(monkeypatch):
    conn = sqlite3.connect(":memory:")
    _create_contests_table(conn)
    update_contests.create_notifications_table(conn)
    update_contests.create_vip_presence_table(conn)
    start_date = (datetime.datetime.now() + datetime.timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        """
        INSERT INTO contests (
            dk_id, sport, name, start_date, draft_group, total_prizes, entries,
            positions_paid, entry_fee, entry_count, max_entry_count, completed, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (124, "NBA", "Test Contest", start_date, 1, 0, 0, None, 25, 0, 0, 0, None),
    )
    conn.commit()

    class DummySport:
        name = "NBA"
        sheet_min_entry_fee = 25
        keyword = "%"

    resolver_calls: list[int] = []

    def fake_resolver(conn, *, dk, dk_id, start_date, vip_names):
        resolver_calls.append(dk_id)
        return update_contests.VIP_UNKNOWN

    sender = _make_sender()
    monkeypatch.setattr(update_contests, "_build_discord_sender", lambda: sender)
    monkeypatch.setattr(update_contests, "_sport_choices", lambda: {"nba": DummySport})
    monkeypatch.setattr(update_contests, "_warning_schedule_for", lambda _sport: [25])
    monkeypatch.setattr(update_contests, "_resolve_vip_presence", fake_resolver)
    monkeypatch.setattr(update_contests, "_maybe_send_soft_finish_announcement", lambda *args, **kwargs: None)

    update_contests.check_contests_for_completion(conn)

    assert resolver_calls == [124]
    assert len(sender.messages) == 1
    assert "Contest starting soon (25m)" in sender.messages[0]
    assert update_contests.db_has_notification(conn, 124, "warning:25") is True


def test_warning_notification_sent_when_draftkings_client_init_fails(monkeypatch):
    conn = sqlite3.connect(":memory:")
    _create_contests_table(conn)
    update_contests.create_notifications_table(conn)
    update_contests.create_vip_presence_table(conn)
    start_date = (datetime.datetime.now() + datetime.timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        """
        INSERT INTO contests (
            dk_id, sport, name, start_date, draft_group, total_prizes, entries,
            positions_paid, entry_fee, entry_count, max_entry_count, completed, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (125, "NBA", "Init Failure Contest", start_date, 1, 0, 0, None, 25, 0, 0, 0, None),
    )
    conn.commit()

    class DummySport:
        name = "NBA"
        sheet_min_entry_fee = 25
        keyword = "%"

    class FailingDraftkings:
        def __init__(self):
            raise RuntimeError("can't find cookies file")

    sender = _make_sender()
    monkeypatch.setattr(update_contests, "_build_discord_sender", lambda: sender)
    monkeypatch.setattr(update_contests, "_sport_choices", lambda: {"nba": DummySport})
    monkeypatch.setattr(update_contests, "_warning_schedule_for", lambda _sport: [25])
    monkeypatch.setattr(update_contests, "Draftkings", FailingDraftkings)
    monkeypatch.setattr(update_contests, "_maybe_send_soft_finish_announcement", lambda *args, **kwargs: None)

    update_contests.check_contests_for_completion(conn)

    assert len(sender.messages) == 1
    assert "Contest starting soon (25m)" in sender.messages[0]
    assert update_contests.db_has_notification(conn, 125, "warning:25") is True


def test_live_notification_suppressed_when_vip_presence_absent(monkeypatch):
    conn = sqlite3.connect(":memory:")
    _create_contests_table(conn)
    update_contests.create_notifications_table(conn)
    update_contests.create_vip_presence_table(conn)
    start_date = "2026-03-29 12:00:00"
    conn.execute(
        """
        INSERT INTO contests (
            dk_id, sport, name, start_date, draft_group, total_prizes, entries,
            positions_paid, entry_fee, entry_count, max_entry_count, completed, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (222, "NBA", "Live Contest", start_date, 55, 0, 0, None, 25, 0, 0, 0, "SCHEDULED"),
    )
    conn.commit()

    class DummySport:
        name = "NBA"
        sheet_min_entry_fee = 25
        keyword = "%"

    sender = _make_sender()
    monkeypatch.setattr(update_contests, "_build_discord_sender", lambda: sender)
    monkeypatch.setattr(update_contests, "_sport_choices", lambda: {"nba": DummySport})
    monkeypatch.setattr(update_contests, "_warning_schedule_for", lambda _sport: [])
    monkeypatch.setattr(
        update_contests,
        "_resolve_vip_presence",
        lambda *_args, **_kwargs: update_contests.VIP_ABSENT,
    )
    monkeypatch.setattr(
        update_contests,
        "db_get_incomplete_contests",
        lambda _c: [(222, 55, 0, None, "SCHEDULED", 0, "Live Contest", start_date, "NBA")],
    )
    monkeypatch.setattr(
        update_contests,
        "get_contest_data",
        lambda _id: {"positions_paid": 100, "status": "LIVE", "completed": 0, "entries": 400},
    )
    monkeypatch.setattr(
        update_contests,
        "db_get_live_contest",
        lambda *_a, **_k: (222, "Live Contest", 55, 100, start_date),
    )
    monkeypatch.setattr(update_contests, "_maybe_send_soft_finish_announcement", lambda *args, **kwargs: None)

    update_contests.check_contests_for_completion(conn)

    assert sender.messages == []
    assert update_contests.db_has_notification(conn, 222, "live") is False


def test_completed_notification_suppressed_when_vip_presence_absent(monkeypatch):
    conn = sqlite3.connect(":memory:")
    _create_contests_table(conn)
    update_contests.create_notifications_table(conn)
    update_contests.create_vip_presence_table(conn)
    start_date = "2026-03-29 12:00:00"
    conn.execute(
        """
        INSERT INTO contests (
            dk_id, sport, name, start_date, draft_group, total_prizes, entries,
            positions_paid, entry_fee, entry_count, max_entry_count, completed, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (333, "NBA", "Completed Contest", start_date, 65, 0, 0, None, 25, 0, 0, 0, "SCHEDULED"),
    )
    update_contests.db_insert_notification(conn, 333, "live")
    conn.commit()

    class DummySport:
        name = "NBA"
        sheet_min_entry_fee = 25
        keyword = "%"

    sender = _make_sender()
    monkeypatch.setattr(update_contests, "_build_discord_sender", lambda: sender)
    monkeypatch.setattr(update_contests, "_sport_choices", lambda: {"nba": DummySport})
    monkeypatch.setattr(update_contests, "_warning_schedule_for", lambda _sport: [])
    monkeypatch.setattr(
        update_contests,
        "_resolve_vip_presence",
        lambda *_args, **_kwargs: update_contests.VIP_ABSENT,
    )
    monkeypatch.setattr(
        update_contests,
        "db_get_incomplete_contests",
        lambda _c: [(333, 65, 0, None, "SCHEDULED", 0, "Completed Contest", start_date, "NBA")],
    )
    monkeypatch.setattr(
        update_contests,
        "get_contest_data",
        lambda _id: {"positions_paid": 100, "status": "COMPLETED", "completed": 1, "entries": 400},
    )
    monkeypatch.setattr(
        update_contests,
        "db_get_live_contest",
        lambda *_a, **_k: (333, "Completed Contest", 65, 100, start_date),
    )
    monkeypatch.setattr(update_contests, "_maybe_send_soft_finish_announcement", lambda *args, **kwargs: None)

    update_contests.check_contests_for_completion(conn)

    assert sender.messages == []
    assert update_contests.db_has_notification(conn, 333, "completed") is False
