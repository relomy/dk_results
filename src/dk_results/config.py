"""dk_results configuration helpers."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from dfs_common import config as common_config
from dotenv import load_dotenv

from dk_results.paths import repo_file

logger = logging.getLogger(__name__)

DEFAULT_CONTEST_WARNING_MINUTES = 25

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


def _optional_channel_id(value: Any) -> int | None:
    try:
        return common_config.parse_int(value)
    except ValueError:
        logger.warning("DISCORD_CHANNEL_ID is not a valid integer: %s", value)
        return None


@dataclass(frozen=True)
class ResolvedSettings:
    """Scalar settings resolved env > config.json > default."""

    spreadsheet_id: str | None = field(default=None, metadata={"env": "SPREADSHEET_ID"})
    dfs_state_dir: str | None = field(default=None, metadata={"env": "DFS_STATE_DIR"})
    sheet_gids_file: str = field(default="sheet_gids.yaml", metadata={"env": "SHEET_GIDS_FILE"})
    discord_notifications_enabled: bool = field(
        default=True,
        metadata={"env": "DISCORD_NOTIFICATIONS_ENABLED", "parser": common_config.parse_bool},
    )
    contest_warning_minutes: int = field(
        default=DEFAULT_CONTEST_WARNING_MINUTES,
        metadata={"env": "CONTEST_WARNING_MINUTES", "parser": common_config.parse_int},
    )
    warning_schedule_file: str = field(
        default="contest_warning_schedules.yaml", metadata={"env": "CONTEST_WARNING_SCHEDULE_FILE"}
    )
    dashboard_base_url: str | None = field(default=None, metadata={"env": "DASHBOARD_BASE_URL"})
    bot_token: str | None = field(default=None, metadata={"env": "DISCORD_BOT_TOKEN"})
    discord_log_file: str | None = field(default=None, metadata={"env": "DISCORD_LOG_FILE"})
    allowed_channel_id: int | None = field(
        default=None, metadata={"env": "DISCORD_CHANNEL_ID", "parser": _optional_channel_id}
    )


@dataclass(frozen=True)
class RuntimeSettings:
    """Everything an executable needs from configuration, resolved once per process."""

    spreadsheet_id: str | None
    dfs_state_dir: str | None
    sheet_gids_file: str
    sheet_gid_map: dict[str, int]
    discord_notifications_enabled: bool
    contest_warning_minutes: int
    warning_schedule_file: str
    warning_schedules: dict[str, list[int]]
    default_warning_schedule: list[int]
    dashboard_base_url: str | None
    bot_token: str | None
    discord_log_file: str | None
    allowed_channel_id: int | None


def load_settings() -> ResolvedSettings:
    config_data = common_config.load_json_config(repo_file("config.json"))
    return common_config.resolve_settings(ResolvedSettings, config_data)


def apply_environment_defaults(settings: ResolvedSettings) -> None:
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


def load_and_apply_settings() -> ResolvedSettings:
    _clear_empty_environment_settings()
    load_dotenv(dotenv_path=repo_file(".env"), override=False)
    settings = load_settings()
    apply_environment_defaults(settings)
    return settings


def _resolve_repo_path(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else repo_file(raw)


def _read_yaml_dict(path: Path, label: str) -> dict[Any, Any] | None:
    """Return a YAML mapping, or None when the file is missing, unparsable or not a mapping."""
    if not path.is_file():
        logger.info("%s not found at %s.", label, path)
        return None
    try:
        data = yaml.safe_load(path.read_text()) or {}
    except Exception:
        logger.warning("Failed to load %s from %s", label, path)
        return None
    if not isinstance(data, dict):
        logger.warning("%s at %s did not contain a dict.", label, path)
        return None
    return data


def _load_sheet_gid_map(sheet_gids_file: str) -> dict[str, int]:
    """Load a sheet title -> gid map from the configured YAML file."""
    if not sheet_gids_file:
        logger.info("SHEET_GIDS_FILE not set; sheet links disabled.")
        return {}
    data = _read_yaml_dict(_resolve_repo_path(sheet_gids_file), "Sheet gid map")
    if data is None:
        return {}
    return {key: value for key, value in data.items() if isinstance(key, str) and isinstance(value, int)}


def _normalize_warning_schedule(items: Any, *, key: str) -> list[int]:
    """Normalize a schedule list, logging and dropping invalid entries."""
    if not isinstance(items, list):
        logger.warning("Invalid warning schedule for %s; expected list.", key)
        return []
    normalized = {item for item in items if isinstance(item, int) and item > 0}
    invalid = len(items) - sum(1 for item in items if isinstance(item, int) and item > 0)
    if invalid:
        logger.warning("Dropped %d invalid warning schedule entries for %s.", invalid, key)
    return sorted(normalized)


def _load_warning_schedules(schedule_file: str, default_schedule: list[int]) -> dict[str, list[int]]:
    """Load per-sport warning schedules from YAML, always including a ``default`` entry."""
    data = _read_yaml_dict(_resolve_repo_path(schedule_file), "Warning schedules") or {}
    schedules: dict[str, list[int]] = {}
    for key, value in data.items():
        if not isinstance(key, str) or not key:
            logger.warning("Ignoring invalid warning schedule key: %s", key)
            continue
        normalized = _normalize_warning_schedule(value, key=key)
        if normalized:
            schedules[key.lower()] = normalized
    schedules.setdefault("default", default_schedule)
    return schedules


def load_runtime_settings() -> RuntimeSettings:
    """Bootstrap the process and return the fully resolved runtime settings."""
    resolved = load_and_apply_settings()
    default_schedule = [resolved.contest_warning_minutes]
    return RuntimeSettings(
        spreadsheet_id=resolved.spreadsheet_id,
        dfs_state_dir=resolved.dfs_state_dir,
        sheet_gids_file=resolved.sheet_gids_file,
        sheet_gid_map=_load_sheet_gid_map(resolved.sheet_gids_file),
        discord_notifications_enabled=resolved.discord_notifications_enabled,
        contest_warning_minutes=resolved.contest_warning_minutes,
        warning_schedule_file=resolved.warning_schedule_file,
        warning_schedules=_load_warning_schedules(resolved.warning_schedule_file, default_schedule),
        default_warning_schedule=default_schedule,
        dashboard_base_url=resolved.dashboard_base_url,
        bot_token=resolved.bot_token,
        discord_log_file=resolved.discord_log_file,
        allowed_channel_id=resolved.allowed_channel_id,
    )
