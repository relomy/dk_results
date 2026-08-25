"""Tests for the update_contests CLI composition root.

The contest-completion workflow itself now lives in
`dk_results.completion_processor` (see tests/test_completion_processor.py). This
module covers what remains here: config loading, sender wiring, processor
assembly, and ``main()``.
"""

import runpy
import sqlite3
import sys

import pytest
import yaml

import dk_results.cli.update_contests as update_contests


def test_is_notifications_enabled_false(monkeypatch):
    monkeypatch.setattr(update_contests, "DISCORD_NOTIFICATIONS_ENABLED", "false")
    assert update_contests._is_notifications_enabled() is False


def test_sport_choices_filters_invalid():
    class DummySport(update_contests.Sport):
        name = ""

    choices = update_contests._sport_choices()
    assert "" not in choices


def test_build_discord_sender_ignores_notifications_flag(monkeypatch):
    # The sender is built from credentials alone; whether notifications are
    # enabled is a separate decision injected into the processor. A disabled run
    # can still have a sender wired (held idle by the processor's gate).
    monkeypatch.setattr(update_contests, "DISCORD_NOTIFICATIONS_ENABLED", "false")
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "tok")
    monkeypatch.setenv("DISCORD_CHANNEL_ID", "123")

    sender = update_contests._build_discord_sender()

    assert isinstance(sender, update_contests.DiscordRest)


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


def test_build_discord_sender_success_path(monkeypatch):
    monkeypatch.setattr(update_contests, "DISCORD_NOTIFICATIONS_ENABLED", "true")
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "tok")
    monkeypatch.setenv("DISCORD_CHANNEL_ID", "123")

    sender = update_contests._build_discord_sender()

    assert isinstance(sender, update_contests.DiscordRest)
    assert sender.token == "tok"
    assert sender.channel_id == 123


# ── Sheet gid map ────────────────────────────────────────────────────────────


def test_load_sheet_gid_map_missing_file(tmp_path, monkeypatch):
    monkeypatch.setattr(update_contests, "SHEET_GIDS_FILE", str(tmp_path / "missing.yaml"))
    assert update_contests._load_sheet_gid_map() == {}


def test_load_sheet_gid_map_valid_entries(tmp_path, monkeypatch):
    path = tmp_path / "gids.yaml"
    path.write_text("NBA: 10\nbad: x\n42: 3\n")
    monkeypatch.setattr(update_contests, "SHEET_GIDS_FILE", str(path))

    assert update_contests._load_sheet_gid_map() == {"NBA": 10}


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


# ── Warning schedule map ─────────────────────────────────────────────────────


def test_normalize_warning_schedule_non_list():
    assert update_contests._normalize_warning_schedule("bad", key="nba") == []


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


def test_load_warning_schedule_map_non_dict(tmp_path, monkeypatch):
    path = tmp_path / "sched.yaml"
    path.write_text("- 1\n")
    monkeypatch.setenv(update_contests.WARNING_SCHEDULE_FILE_ENV, str(path))
    monkeypatch.setattr(update_contests.yaml, "safe_load", lambda _text: ["bad"])

    result = update_contests._load_warning_schedule_map()

    assert result == {"default": update_contests._DEFAULT_WARNING_SCHEDULE}


# ── VIP loading ──────────────────────────────────────────────────────────────


def test_load_vips_reads_names(tmp_path, monkeypatch):
    path = tmp_path / "vips.yaml"
    path.write_text("- FooBar\n- ' '\n- Alpha\n")
    monkeypatch.setattr(update_contests, "repo_file", lambda *_parts: path)

    assert update_contests._load_vips() == ["FooBar", "Alpha"]


def test_load_vips_missing_file(tmp_path, monkeypatch):
    monkeypatch.setattr(update_contests, "repo_file", lambda *_parts: tmp_path / "missing.yaml")
    assert update_contests._load_vips() == []


# ── Processor assembly ───────────────────────────────────────────────────────


def test_build_completion_processor_wires_collaborators(monkeypatch):
    conn = sqlite3.connect(":memory:")

    class FakeSender:
        def send_message(self, message):  # pragma: no cover - not called here
            pass

    sender = FakeSender()
    fake_client = object()
    monkeypatch.setattr(update_contests, "DISCORD_NOTIFICATIONS_ENABLED", "true")
    monkeypatch.setattr(update_contests, "_build_discord_sender", lambda: sender)
    monkeypatch.setattr(update_contests, "_load_vips", lambda: ["FooBar"])
    monkeypatch.setattr(update_contests, "DraftKings", lambda: fake_client)

    processor = update_contests._build_completion_processor(conn)

    assert processor._results is fake_client
    assert processor._sender is sender
    assert processor._presence is not None
    assert processor._config.vips == ["FooBar"]


def test_build_completion_processor_uses_stub_results_when_client_init_fails(monkeypatch):
    conn = sqlite3.connect(":memory:")

    class FakeSender:
        def send_message(self, message):  # pragma: no cover - not called here
            pass

    def boom():
        raise RuntimeError("no cookies")

    monkeypatch.setattr(update_contests, "_build_discord_sender", lambda: FakeSender())
    monkeypatch.setattr(update_contests, "_load_vips", lambda: ["FooBar"])
    monkeypatch.setattr(update_contests, "DraftKings", boom)

    processor = update_contests._build_completion_processor(conn)

    assert isinstance(processor._results, update_contests._UnavailableContestResults)
    assert processor._presence is None


def test_build_completion_processor_injects_enabled_flag(monkeypatch):
    conn = sqlite3.connect(":memory:")

    class FakeSender:
        def send_message(self, message):  # pragma: no cover - not called here
            pass

    monkeypatch.setattr(update_contests, "DISCORD_NOTIFICATIONS_ENABLED", "true")
    monkeypatch.setattr(update_contests, "_build_discord_sender", lambda: FakeSender())
    monkeypatch.setattr(update_contests, "DraftKings", lambda: object())

    processor = update_contests._build_completion_processor(conn)

    assert processor._config.notifications_enabled is True
    assert processor._presence is not None


def test_build_completion_processor_disabled_wires_idle_sender(monkeypatch):
    # A disabled run still constructs the processor with a wired sender, but the
    # explicit gate is off, presence is skipped, and no VIPs are resolved.
    conn = sqlite3.connect(":memory:")

    class FakeSender:
        def send_message(self, message):  # pragma: no cover - not called here
            pass

    sender = FakeSender()
    monkeypatch.setattr(update_contests, "DISCORD_NOTIFICATIONS_ENABLED", "false")
    monkeypatch.setattr(update_contests, "_build_discord_sender", lambda: sender)
    monkeypatch.setattr(update_contests, "_load_vips", lambda: ["FooBar"])
    monkeypatch.setattr(update_contests, "DraftKings", lambda: object())

    processor = update_contests._build_completion_processor(conn)

    assert processor._config.notifications_enabled is False
    assert processor._sender is sender
    assert processor._presence is None
    assert processor._config.vips == []


def test_check_contests_for_completion_delegates_to_processor(monkeypatch):
    conn = sqlite3.connect(":memory:")
    ran = {}

    class FakeProcessor:
        def run(self, passed_conn):
            ran["conn"] = passed_conn

    monkeypatch.setattr(update_contests, "_build_completion_processor", lambda _c: FakeProcessor())

    update_contests.check_contests_for_completion(conn)

    assert ran["conn"] is conn


# ── main() ───────────────────────────────────────────────────────────────────


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


def test_main_help_exits_without_runtime(monkeypatch):
    def boom(_path):
        raise AssertionError("sqlite connect should not run for --help")

    monkeypatch.setattr(update_contests.sqlite3, "connect", boom)

    with pytest.raises(SystemExit) as exc:
        update_contests.main(["--help"])

    assert exc.value.code == 0


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
