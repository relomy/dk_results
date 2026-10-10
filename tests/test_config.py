import json
from types import SimpleNamespace

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


_SETTINGS_ENV_KEYS = (
    "SPREADSHEET_ID",
    "DFS_STATE_DIR",
    "SHEET_GIDS_FILE",
    "DISCORD_NOTIFICATIONS_ENABLED",
    "CONTEST_WARNING_MINUTES",
)


def _clear_settings_env(monkeypatch):
    for key in _SETTINGS_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def test_load_settings_defaults_without_env_or_config(monkeypatch, tmp_path):
    _clear_settings_env(monkeypatch)
    monkeypatch.setattr(config, "repo_file", lambda name: tmp_path / "missing.json")

    assert config.load_settings() == config.DkResultsSettings(
        spreadsheet_id=None,
        dfs_state_dir=None,
        sheet_gids_file="sheet_gids.yaml",
        discord_notifications_enabled=True,
        contest_warning_minutes=25,
    )


def test_load_settings_reads_config_json(monkeypatch, tmp_path):
    _clear_settings_env(monkeypatch)
    config_file = tmp_path / "config.json"
    config_file.write_text(
        json.dumps(
            {
                "spreadsheet_id": "cfg-sheet",
                "dfs_state_dir": "cfg-state",
                "sheet_gids_file": "cfg-gids.yaml",
                "discord_notifications_enabled": False,
                "contest_warning_minutes": 40,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "repo_file", lambda name: config_file)

    settings = config.load_settings()

    assert settings.spreadsheet_id == "cfg-sheet"
    assert settings.dfs_state_dir == "cfg-state"
    assert settings.sheet_gids_file == "cfg-gids.yaml"
    assert settings.discord_notifications_enabled is False
    assert settings.contest_warning_minutes == 40


def test_load_settings_env_overrides_config_and_parses(monkeypatch, tmp_path):
    config_file = tmp_path / "config.json"
    config_file.write_text(
        json.dumps(
            {
                "spreadsheet_id": "cfg-sheet",
                "dfs_state_dir": "cfg-state",
                "sheet_gids_file": "cfg-gids.yaml",
                "discord_notifications_enabled": True,
                "contest_warning_minutes": 40,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "repo_file", lambda name: config_file)
    monkeypatch.setenv("SPREADSHEET_ID", "env-sheet")
    monkeypatch.setenv("DFS_STATE_DIR", "env-state")
    monkeypatch.setenv("SHEET_GIDS_FILE", "env-gids.yaml")
    monkeypatch.setenv("DISCORD_NOTIFICATIONS_ENABLED", "false")
    monkeypatch.setenv("CONTEST_WARNING_MINUTES", "30")

    settings = config.load_settings()

    assert settings.spreadsheet_id == "env-sheet"
    assert settings.dfs_state_dir == "env-state"
    assert settings.sheet_gids_file == "env-gids.yaml"
    assert settings.discord_notifications_enabled is False
    assert settings.contest_warning_minutes == 30
