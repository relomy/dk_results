"""Tests for the update_contests CLI composition root.

The contest-completion workflow itself now lives in
`dk_results.completion_processor` (see tests/test_completion_processor.py). This
module covers what remains here: sender wiring, processor assembly, and
``main()``. Sheet-gid-map and warning-schedule YAML parsing now live in
`dk_results.config` and are tested once there (tests/test_config.py); this
file keeps only thin wiring tests that construct a `RuntimeSettings` directly
and assert `update_contests.py` threads it through correctly.
"""

import runpy
import sqlite3
import sys

import pytest

import dk_results.cli.update_contests as update_contests
from dk_results.config import RuntimeSettings


@pytest.fixture
def memory_conn():
    conn = sqlite3.connect(":memory:")
    try:
        yield conn
    finally:
        conn.close()


def _settings(**overrides) -> RuntimeSettings:
    defaults = dict(
        spreadsheet_id="sheet",
        dfs_state_dir=None,
        sheet_gids_file="sheet_gids.yaml",
        discord_notifications_enabled=True,
        contest_warning_minutes=25,
        warning_schedule_file="contest_warning_schedules.yaml",
        bot_token=None,
        discord_log_file=None,
        allowed_channel_id=None,
        sheet_gid_map={"NBA": 10},
        warning_schedules={"default": [25]},
        default_warning_schedule=[25],
    )
    defaults.update(overrides)
    return RuntimeSettings(**defaults)


def test_sport_choices_filters_invalid():
    class DummySport(update_contests.Sport):
        name = ""

    choices = update_contests._sport_choices()
    assert "" not in choices


def test_build_discord_sender_missing_config(monkeypatch):
    monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
    monkeypatch.delenv("DISCORD_CHANNEL_ID", raising=False)
    assert update_contests._build_discord_sender() is None


def test_build_discord_sender_invalid_channel(monkeypatch):
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "tok")
    monkeypatch.setenv("DISCORD_CHANNEL_ID", "bad")
    assert update_contests._build_discord_sender() is None


def test_build_discord_sender_success_path(monkeypatch):
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "tok")
    monkeypatch.setenv("DISCORD_CHANNEL_ID", "123")

    sender = update_contests._build_discord_sender()

    assert isinstance(sender, update_contests.DiscordRest)
    assert sender.token == "tok"
    assert sender.channel_id == 123


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


def test_build_completion_processor_wires_collaborators(monkeypatch, memory_conn):
    conn = memory_conn

    class FakeSender:
        def send_message(self, message):  # pragma: no cover - not called here
            pass

    sender = FakeSender()
    fake_client = object()
    monkeypatch.setattr(update_contests, "_build_discord_sender", lambda: sender)
    monkeypatch.setattr(update_contests, "_load_vips", lambda: ["FooBar"])
    monkeypatch.setattr(update_contests, "DraftKings", lambda: fake_client)

    processor = update_contests._build_completion_processor(conn, _settings())

    assert processor._results is fake_client
    assert processor._sender is sender
    assert processor._presence is not None
    assert processor._config.vips == ["FooBar"]


def test_build_completion_processor_threads_settings_into_config(monkeypatch, memory_conn):
    monkeypatch.setattr(update_contests, "_build_discord_sender", lambda: None)
    monkeypatch.setattr(update_contests, "DraftKings", lambda: object())

    processor = update_contests._build_completion_processor(memory_conn, _settings())

    assert processor._config.spreadsheet_id == "sheet"
    assert processor._config.sheet_gid_map == {"NBA": 10}


def test_build_completion_processor_uses_stub_results_when_client_init_fails(monkeypatch, memory_conn):
    conn = memory_conn

    class FakeSender:
        def send_message(self, message):  # pragma: no cover - not called here
            pass

    def boom():
        raise RuntimeError("no cookies")

    monkeypatch.setattr(update_contests, "_build_discord_sender", lambda: FakeSender())
    monkeypatch.setattr(update_contests, "_load_vips", lambda: ["FooBar"])
    monkeypatch.setattr(update_contests, "DraftKings", boom)

    processor = update_contests._build_completion_processor(conn, _settings())

    assert isinstance(processor._results, update_contests._UnavailableContestResults)
    assert processor._presence is None


def test_build_completion_processor_injects_enabled_flag(monkeypatch, memory_conn):
    conn = memory_conn

    class FakeSender:
        def send_message(self, message):  # pragma: no cover - not called here
            pass

    monkeypatch.setattr(update_contests, "_build_discord_sender", lambda: FakeSender())
    monkeypatch.setattr(update_contests, "DraftKings", lambda: object())

    processor = update_contests._build_completion_processor(conn, _settings(discord_notifications_enabled=True))

    assert processor._config.notifications_enabled is True
    assert processor._presence is not None


def test_build_completion_processor_disabled_wires_idle_sender(monkeypatch, memory_conn):
    # A disabled run still constructs the processor with a wired sender, but the
    # explicit gate is off, presence is skipped, and no VIPs are resolved.
    conn = memory_conn

    class FakeSender:
        def send_message(self, message):  # pragma: no cover - not called here
            pass

    sender = FakeSender()
    monkeypatch.setattr(update_contests, "_build_discord_sender", lambda: sender)
    monkeypatch.setattr(update_contests, "_load_vips", lambda: ["FooBar"])
    monkeypatch.setattr(update_contests, "DraftKings", lambda: object())

    processor = update_contests._build_completion_processor(conn, _settings(discord_notifications_enabled=False))

    assert processor._config.notifications_enabled is False
    assert processor._sender is sender
    assert processor._presence is None
    assert processor._config.vips == []


def test_check_contests_for_completion_delegates_to_processor(monkeypatch, memory_conn):
    conn = memory_conn
    ran = {}

    class FakeProcessor:
        def run(self, passed_conn):
            ran["conn"] = passed_conn

    monkeypatch.setattr(update_contests, "_build_completion_processor", lambda _c, _s: FakeProcessor())

    update_contests.check_contests_for_completion(conn, _settings())

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
    monkeypatch.setattr(update_contests, "check_contests_for_completion", lambda _c, _s: None)

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
        lambda c, s: called.setdefault("ok", True),
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
