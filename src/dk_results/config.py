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


@dataclass(frozen=True)
class _EnvSettings:
    """Scalar configuration resolved from env / config.json / field defaults.

    Internal to this module. `load_runtime_settings()` combines this with
    file-derived state (sheet gid map, warning schedules) into the public
    `RuntimeSettings` both `update_contests.py` and `discord_bot.py` consume.
    """

    spreadsheet_id: str | None = field(default=None, metadata={"env": "SPREADSHEET_ID"})
    dfs_state_dir: str | None = field(default=None, metadata={"env": "DFS_STATE_DIR"})
    sheet_gids_file: str = field(default="sheet_gids.yaml", metadata={"env": "SHEET_GIDS_FILE"})
    discord_notifications_enabled: bool = field(
        default=True,
        metadata={"env": "DISCORD_NOTIFICATIONS_ENABLED", "parser": common_config.parse_bool},
    )
    contest_warning_minutes: int = field(
        default=25,
        metadata={"env": "CONTEST_WARNING_MINUTES", "parser": common_config.parse_int},
    )
    warning_schedule_file: str = field(
        default="contest_warning_schedules.yaml",
        metadata={"env": "CONTEST_WARNING_SCHEDULE_FILE"},
    )
    bot_token: str | None = field(default=None, metadata={"env": "DISCORD_BOT_TOKEN"})
    discord_log_file: str | None = field(default=None, metadata={"env": "DISCORD_LOG_FILE"})
    discord_channel_id: str | None = field(default=None, metadata={"env": "DISCORD_CHANNEL_ID"})


def load_settings() -> _EnvSettings:
    config_data = common_config.load_json_config(repo_file("config.json"))
    return common_config.resolve_settings(_EnvSettings, config_data)


def apply_environment_defaults(settings: _EnvSettings) -> None:
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


def load_and_apply_settings() -> _EnvSettings:
    """Runtime bootstrap: load `.env`, resolve settings, apply unset env defaults.

    Every dk_results executable calls this before reading configuration-dependent
    values (see ADR-0009). Several callers (`db_main.py`, `sheets_service.py`,
    and others) read `DFS_STATE_DIR`/`SPREADSHEET_ID`/etc. straight from
    `os.environ` rather than through `RuntimeSettings`, so this keeps applying
    resolved values back onto the process environment independently of
    `load_runtime_settings()` below.
    """
    _clear_empty_environment_settings()
    load_dotenv(dotenv_path=repo_file(".env"), override=False)
    settings = load_settings()
    apply_environment_defaults(settings)
    return settings


# ── RuntimeSettings ──────────────────────────────────────────────────────────
#
# The single seam `update_contests.py` and `discord_bot.py` construct once at
# startup and thread through, replacing each file's own module globals and
# private YAML loaders for sheet gids and warning schedules.


@dataclass(frozen=True)
class RuntimeSettings:
    """Resolved runtime configuration for a dk_results executable.

    Constructed once via `load_runtime_settings()`. A field unused by one
    caller (e.g. `warning_schedules` in the Discord bot, `bot_token` in
    `update_contests.py`) stays on this one shape rather than forking into a
    second type per caller.
    """

    spreadsheet_id: str | None
    dfs_state_dir: str | None
    sheet_gids_file: str
    discord_notifications_enabled: bool
    contest_warning_minutes: int
    warning_schedule_file: str
    bot_token: str | None
    discord_log_file: str | None
    allowed_channel_id: int | None
    sheet_gid_map: dict[str, int]
    warning_schedules: dict[str, list[int]]
    default_warning_schedule: list[int]


def _resolved_path(configured: str) -> Path:
    path = Path(configured)
    return path if path.is_absolute() else repo_file(configured)


def _load_sheet_gid_map(sheet_gids_file: str) -> dict[str, int]:
    """Load a sheet title -> gid map from the configured YAML file."""
    if not sheet_gids_file:
        return {}
    path = _resolved_path(sheet_gids_file)
    if not path.is_file():
        return {}
    try:
        data = yaml.safe_load(path.read_text()) or {}
    except Exception:
        logger.warning("Failed to load sheet gid map from %s", path)
        return {}
    if not isinstance(data, dict):
        return {}
    return {key: value for key, value in data.items() if isinstance(key, str) and isinstance(value, int)}


def _normalize_warning_schedule(items: Any, *, key: str) -> list[int]:
    """Normalize a schedule list, logging and dropping invalid entries."""
    if not isinstance(items, list):
        logger.warning("Invalid warning schedule for %s; expected list.", key)
        return []
    normalized: set[int] = set()
    invalid = 0
    for item in items:
        if isinstance(item, int) and item > 0:
            normalized.add(item)
        else:
            invalid += 1
    if invalid:
        logger.warning("Dropped %d invalid warning schedule entries for %s.", invalid, key)
    return sorted(normalized)


def _read_warning_schedule_data(path: Path) -> dict[str, Any] | None:
    try:
        data = yaml.safe_load(path.read_text()) or {}
    except Exception:
        logger.warning("Failed to load warning schedules from %s", path)
        return None
    if not isinstance(data, dict):
        logger.warning("Warning schedule file at %s did not contain a dict.", path)
        return None
    return data


def _build_warning_schedules(data: dict[str, Any]) -> dict[str, list[int]]:
    schedules: dict[str, list[int]] = {}
    for key, value in data.items():
        if not isinstance(key, str) or not key:
            logger.warning("Ignoring invalid warning schedule key: %s", key)
            continue
        normalized = _normalize_warning_schedule(value, key=key)
        if normalized:
            schedules[key.lower()] = normalized
    return schedules


def _load_warning_schedule_map(warning_schedule_file: str, default_warning_schedule: list[int]) -> dict[str, list[int]]:
    """Load per-sport warning schedules from YAML."""
    path = _resolved_path(warning_schedule_file)
    if not path.is_file():
        return {"default": default_warning_schedule}
    data = _read_warning_schedule_data(path)
    if data is None:
        return {"default": default_warning_schedule}
    schedules = _build_warning_schedules(data)
    schedules.setdefault("default", default_warning_schedule)
    return schedules


def _parse_channel_id(raw: str | None) -> int | None:
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        logger.warning("DISCORD_CHANNEL_ID is not a valid integer: %s", raw)
        return None


def load_runtime_settings() -> RuntimeSettings:
    """Resolve dk_results' full runtime configuration once, at the executable boundary."""
    env = load_and_apply_settings()
    default_warning_schedule = [env.contest_warning_minutes]
    return RuntimeSettings(
        spreadsheet_id=env.spreadsheet_id,
        dfs_state_dir=env.dfs_state_dir,
        sheet_gids_file=env.sheet_gids_file,
        discord_notifications_enabled=env.discord_notifications_enabled,
        contest_warning_minutes=env.contest_warning_minutes,
        warning_schedule_file=env.warning_schedule_file,
        bot_token=env.bot_token,
        discord_log_file=env.discord_log_file,
        allowed_channel_id=_parse_channel_id(env.discord_channel_id),
        sheet_gid_map=_load_sheet_gid_map(env.sheet_gids_file),
        warning_schedules=_load_warning_schedule_map(env.warning_schedule_file, default_warning_schedule),
        default_warning_schedule=default_warning_schedule,
    )
