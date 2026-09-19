from types import SimpleNamespace

import yaml

from dk_results import config


def test_load_and_apply_settings_uses_process_env_then_dotenv_then_config(monkeypatch, tmp_path):
    dotenv_file = tmp_path / ".env"
    dotenv_file.write_text(
        "DFS_STATE_DIR=dotenv-state\nSPREADSHEET_ID=dotenv-sheet\nSHEET_GIDS_FILE=dotenv-gids.yaml\n",
        encoding="utf-8",
    )
    settings = SimpleNamespace(
        dfs_state_dir="config-state",
        spreadsheet_id="config-sheet",
        sheet_gids_file="config-gids.yaml",
        discord_notifications_enabled=True,
        contest_warning_minutes=30,
    )
    monkeypatch.setattr(config, "repo_file", lambda name: dotenv_file)
    monkeypatch.setattr(config, "load_settings", lambda: settings)
    monkeypatch.setenv("DFS_STATE_DIR", "process-state")
    monkeypatch.setenv("SHEET_GIDS_FILE", "")
    monkeypatch.delenv("SPREADSHEET_ID", raising=False)

    assert config.load_and_apply_settings() is settings

    assert config.os.environ["DFS_STATE_DIR"] == "process-state"
    assert config.os.environ["SPREADSHEET_ID"] == "dotenv-sheet"
    assert config.os.environ["SHEET_GIDS_FILE"] == "dotenv-gids.yaml"


# ── Sheet gid map ────────────────────────────────────────────────────────────
#
# Consolidated from the near-identical `_load_sheet_gid_map` coverage that used
# to live separately in tests/test_update_contests.py and
# tests/bot/test_discord_bot.py, now that the loader lives here once.


def test_load_sheet_gid_map_unset():
    assert config._load_sheet_gid_map("") == {}


def test_load_sheet_gid_map_missing_file(tmp_path):
    assert config._load_sheet_gid_map(str(tmp_path / "missing.yaml")) == {}


def test_load_sheet_gid_map_valid_entries(tmp_path):
    path = tmp_path / "gids.yaml"
    path.write_text("NBA: 10\nbad: x\n42: 3\n")
    assert config._load_sheet_gid_map(str(path)) == {"NBA": 10}


def test_load_sheet_gid_map_safe_load_error(tmp_path, monkeypatch):
    path = tmp_path / "gids.yaml"
    path.write_text("NBA: 10\n")

    def boom(_text):
        raise RuntimeError("boom")

    monkeypatch.setattr(config.yaml, "safe_load", boom)

    assert config._load_sheet_gid_map(str(path)) == {}


def test_load_sheet_gid_map_non_dict(tmp_path, monkeypatch):
    path = tmp_path / "gids.yaml"
    path.write_text("- 1\n")
    monkeypatch.setattr(config.yaml, "safe_load", lambda _text: ["bad"])

    assert config._load_sheet_gid_map(str(path)) == {}


def test_load_sheet_gid_map_relative_path_resolves_against_repo_root(tmp_path, monkeypatch):
    path = tmp_path / "gids.yaml"
    path.write_text("NBA: 10\n")
    monkeypatch.setattr(config, "repo_file", lambda *parts: tmp_path.joinpath(*parts))

    assert config._load_sheet_gid_map("gids.yaml") == {"NBA": 10}


# ── Warning schedule map ─────────────────────────────────────────────────────


def test_normalize_warning_schedule_non_list():
    assert config._normalize_warning_schedule("bad", key="nba") == []


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

    captured = []
    monkeypatch.setattr(
        config.logger,
        "warning",
        lambda message, *args: captured.append(message % args if args else message),
    )
    schedules = config._load_warning_schedule_map(str(schedule_path), [25])

    assert schedules["default"] == [25]
    assert schedules["nba"] == [30, 60]
    assert "nfl" not in schedules
    assert any("warning schedule" in message.lower() for message in captured)


def test_load_warning_schedule_map_missing_file(tmp_path):
    missing = tmp_path / "missing.yaml"
    result = config._load_warning_schedule_map(str(missing), [25])
    assert result == {"default": [25]}


def test_load_warning_schedule_map_invalid_yaml(tmp_path, monkeypatch):
    path = tmp_path / "bad.yaml"
    path.write_text("bad: yaml: :")

    def boom(_text):
        raise RuntimeError("boom")

    monkeypatch.setattr(config.yaml, "safe_load", boom)

    result = config._load_warning_schedule_map(str(path), [25])

    assert result == {"default": [25]}


def test_load_warning_schedule_map_invalid_keys_and_default(tmp_path):
    path = tmp_path / "sched.yaml"
    path.write_text('"": [5]\n1: [10]\nNBA: [10, -1, "bad"]\n')

    result = config._load_warning_schedule_map(str(path), [25])

    assert result["nba"] == [10]
    assert "default" in result


def test_load_warning_schedule_map_non_dict(tmp_path, monkeypatch):
    path = tmp_path / "sched.yaml"
    path.write_text("- 1\n")
    monkeypatch.setattr(config.yaml, "safe_load", lambda _text: ["bad"])

    result = config._load_warning_schedule_map(str(path), [25])

    assert result == {"default": [25]}


# ── Discord channel id ───────────────────────────────────────────────────────
#
# Consolidated from tests/bot/test_discord_bot.py's `_channel_id_from_env`
# coverage, now that channel-id parsing takes its raw value as a parameter
# instead of reading `DISCORD_CHANNEL_ID` itself.


def test_parse_channel_id_valid():
    assert config._parse_channel_id("12345") == 12345


def test_parse_channel_id_unset():
    assert config._parse_channel_id(None) is None


def test_parse_channel_id_invalid(monkeypatch):
    captured = []
    monkeypatch.setattr(
        config.logger,
        "warning",
        lambda message, *args: captured.append(message % args if args else message),
    )

    assert config._parse_channel_id("abc") is None
    assert any("not a valid integer" in msg for msg in captured)


# ── RuntimeSettings ──────────────────────────────────────────────────────────


def test_load_runtime_settings_threads_env_and_files(tmp_path, monkeypatch):
    gids_path = tmp_path / "gids.yaml"
    gids_path.write_text("NBA: 10\n")
    schedule_path = tmp_path / "schedules.yaml"
    schedule_path.write_text(yaml.safe_dump({"NBA": [30, 60]}))

    env = SimpleNamespace(
        spreadsheet_id="sheet",
        dfs_state_dir="/tmp/state",
        sheet_gids_file=str(gids_path),
        discord_notifications_enabled=True,
        contest_warning_minutes=25,
        warning_schedule_file=str(schedule_path),
        bot_token="tok",
        discord_log_file=None,
        discord_channel_id="123",
    )
    monkeypatch.setattr(config, "load_and_apply_settings", lambda: env)

    settings = config.load_runtime_settings()

    assert settings.spreadsheet_id == "sheet"
    assert settings.bot_token == "tok"
    assert settings.allowed_channel_id == 123
    assert settings.sheet_gid_map == {"NBA": 10}
    assert settings.warning_schedules == {"nba": [30, 60], "default": [25]}
    assert settings.default_warning_schedule == [25]
