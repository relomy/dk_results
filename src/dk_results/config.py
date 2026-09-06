"""dk_results configuration helpers."""

from __future__ import annotations

import os

from dfs_common import config as common_config
from dotenv import load_dotenv

from dk_results.paths import repo_file

_MANAGED_ENVIRONMENT_KEYS = (
    "DFS_STATE_DIR",
    "SPREADSHEET_ID",
    "SHEET_GIDS_FILE",
    "DISCORD_NOTIFICATIONS_ENABLED",
    "CONTEST_WARNING_MINUTES",
)


def _clear_empty_environment_settings() -> None:
    """Treat empty managed environment values as unset before dotenv loading."""
    for key in _MANAGED_ENVIRONMENT_KEYS:
        if os.getenv(key) == "":
            os.environ.pop(key)


def load_settings() -> common_config.DkResultsSettings:
    config_data = common_config.load_json_config(repo_file("config.json"))
    return common_config.resolve_dk_results_settings(config_data)


def apply_environment_defaults(settings: common_config.DkResultsSettings) -> None:
    if settings.dfs_state_dir and not os.getenv("DFS_STATE_DIR"):
        os.environ["DFS_STATE_DIR"] = settings.dfs_state_dir
    if settings.spreadsheet_id and not os.getenv("SPREADSHEET_ID"):
        os.environ["SPREADSHEET_ID"] = settings.spreadsheet_id
    if not os.getenv("SHEET_GIDS_FILE") and settings.sheet_gids_file:
        os.environ["SHEET_GIDS_FILE"] = settings.sheet_gids_file
    if not os.getenv("DISCORD_NOTIFICATIONS_ENABLED"):
        os.environ["DISCORD_NOTIFICATIONS_ENABLED"] = "true" if settings.discord_notifications_enabled else "false"
    if not os.getenv("CONTEST_WARNING_MINUTES"):
        os.environ["CONTEST_WARNING_MINUTES"] = str(settings.contest_warning_minutes)


def load_and_apply_settings() -> common_config.DkResultsSettings:
    _clear_empty_environment_settings()
    load_dotenv(dotenv_path=repo_file(".env"), override=False)
    settings = load_settings()
    apply_environment_defaults(settings)
    return settings
