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
