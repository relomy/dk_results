from types import SimpleNamespace

import pytest
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


def _runtime_env(monkeypatch, tmp_path, **env):
    """Point the bootstrap at an empty dotenv/config and set only the given env."""
    monkeypatch.setattr(config, "repo_file", lambda *parts: tmp_path.joinpath(*parts))
    for key in (
        "DFS_STATE_DIR",
        "SPREADSHEET_ID",
        "SHEET_GIDS_FILE",
        "DISCORD_NOTIFICATIONS_ENABLED",
        "CONTEST_WARNING_MINUTES",
        "CONTEST_WARNING_SCHEDULE_FILE",
        "DASHBOARD_BASE_URL",
        "DISCORD_BOT_TOKEN",
        "DISCORD_LOG_FILE",
        "DISCORD_CHANNEL_ID",
    ):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)


def test_load_runtime_settings_resolves_scalars_from_env_and_defaults(monkeypatch, tmp_path):
    _runtime_env(
        monkeypatch,
        tmp_path,
        SPREADSHEET_ID="sheet",
        DISCORD_NOTIFICATIONS_ENABLED="false",
        CONTEST_WARNING_MINUTES="40",
        DASHBOARD_BASE_URL="https://dashboard.example",
        DISCORD_BOT_TOKEN="tok",
        DISCORD_CHANNEL_ID="123",
    )

    settings = config.load_runtime_settings()

    assert (settings.spreadsheet_id, settings.discord_notifications_enabled) == ("sheet", False)
    assert (settings.contest_warning_minutes, settings.default_warning_schedule) == (40, [40])
    assert (settings.dashboard_base_url, settings.bot_token) == ("https://dashboard.example", "tok")
    assert (settings.allowed_channel_id, settings.discord_log_file) == (123, None)
    assert (settings.sheet_gid_map, settings.warning_schedules) == ({}, {"default": [40]})


def test_load_runtime_settings_defaults_when_nothing_set(monkeypatch, tmp_path):
    _runtime_env(monkeypatch, tmp_path)

    settings = config.load_runtime_settings()

    assert settings.discord_notifications_enabled is True
    assert settings.contest_warning_minutes == 25
    assert settings.bot_token is None
    assert settings.allowed_channel_id is None


def test_load_runtime_settings_invalid_channel_id_is_none(monkeypatch, tmp_path):
    _runtime_env(monkeypatch, tmp_path, DISCORD_CHANNEL_ID="bad")

    assert config.load_runtime_settings().allowed_channel_id is None


def test_load_runtime_settings_does_not_warn_about_deprecated_resolver(monkeypatch, tmp_path):
    import warnings

    _runtime_env(monkeypatch, tmp_path)

    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        config.load_runtime_settings()


def test_sheet_gid_map_default_file_absent_is_empty(monkeypatch, tmp_path):
    _runtime_env(monkeypatch, tmp_path)

    assert config.load_runtime_settings().sheet_gid_map == {}


def test_sheet_gid_map_keeps_only_str_to_int_entries(monkeypatch, tmp_path):
    path = tmp_path / "gids.yaml"
    path.write_text("NBA: 10\nbad: x\n42: 3\n")
    _runtime_env(monkeypatch, tmp_path, SHEET_GIDS_FILE=str(path))

    assert config.load_runtime_settings().sheet_gid_map == {"NBA": 10}


def test_sheet_gid_map_resolves_relative_path_against_repo(monkeypatch, tmp_path):
    (tmp_path / "gids.yaml").write_text("NBA: 7\n")
    _runtime_env(monkeypatch, tmp_path, SHEET_GIDS_FILE="gids.yaml")

    assert config.load_runtime_settings().sheet_gid_map == {"NBA": 7}


@pytest.mark.parametrize("content", [None, "- 1\n", "bad: yaml: :"])
def test_sheet_gid_map_missing_non_dict_or_invalid_yaml_is_empty(monkeypatch, tmp_path, content):
    path = tmp_path / "gids.yaml"
    if content is not None:
        path.write_text(content)
    _runtime_env(monkeypatch, tmp_path, SHEET_GIDS_FILE=str(path))

    assert config.load_runtime_settings().sheet_gid_map == {}


def test_warning_schedules_normalize_and_drop_invalid_entries(monkeypatch, tmp_path, caplog):
    path = tmp_path / "sched.yaml"
    path.write_text(yaml.safe_dump({"default": [25, "bad", -5, 25], "NBA": [60, 30, 30], "NFL": "oops"}))
    _runtime_env(monkeypatch, tmp_path, CONTEST_WARNING_SCHEDULE_FILE=str(path))

    with caplog.at_level("WARNING"):
        schedules = config.load_runtime_settings().warning_schedules

    assert schedules["default"] == [25]
    assert schedules["nba"] == [30, 60]
    assert "nfl" not in schedules
    assert "warning schedule" in caplog.text.lower()


def test_warning_schedules_invalid_keys_and_missing_default(monkeypatch, tmp_path):
    path = tmp_path / "sched.yaml"
    path.write_text('"": [5]\n1: [10]\nNBA: [10, -1, "bad"]\n')
    _runtime_env(monkeypatch, tmp_path, CONTEST_WARNING_SCHEDULE_FILE=str(path), CONTEST_WARNING_MINUTES="30")

    schedules = config.load_runtime_settings().warning_schedules

    assert schedules == {"nba": [10], "default": [30]}


@pytest.mark.parametrize("content", [None, "- 1\n", "bad: yaml: :"])
def test_warning_schedules_missing_non_dict_or_invalid_yaml_use_default(monkeypatch, tmp_path, content):
    path = tmp_path / "sched.yaml"
    if content is not None:
        path.write_text(content)
    _runtime_env(monkeypatch, tmp_path, CONTEST_WARNING_SCHEDULE_FILE=str(path))

    assert config.load_runtime_settings().warning_schedules == {"default": [25]}
