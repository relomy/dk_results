import datetime
import runpy
import sqlite3

import pytest
import yaml

import dk_results.cli.update_contests as update_contests


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
    runpy.run_module("dk_results.cli.update_contests", run_name="__main__")


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
