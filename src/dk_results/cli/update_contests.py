import argparse
import logging
import os
import sqlite3
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import requests
import yaml
from dfs_common import contests, state

from dk_results.bot.discord_rest import DiscordRest
from dk_results.completion_processor import CompletionProcessor, CompletionProcessorConfig
from dk_results.config import load_and_apply_settings
from dk_results.domain.sport import Sport, get_sport_choices
from dk_results.draftkings import DraftKings
from dk_results.logging import configure_logging
from dk_results.notifications.vip_presence import VipPresence
from dk_results.paths import repo_file
from dk_results.persistence.contestdatabase import ContestDatabase
from dk_results.persistence.notification_store import NotificationStore

logger = logging.getLogger(__name__)

# constants
DISCORD_NOTIFICATIONS_ENABLED = "true"
SPREADSHEET_ID: str | None = None
SHEET_GIDS_FILE = str(repo_file("sheet_gids.yaml"))
CONTEST_WARNING_MINUTES = 25
WARNING_SCHEDULE_FILE_ENV = "CONTEST_WARNING_SCHEDULE_FILE"
DEFAULT_WARNING_SCHEDULE_FILE = str(repo_file("contest_warning_schedules.yaml"))
_DEFAULT_WARNING_SCHEDULE = [CONTEST_WARNING_MINUTES]

SPORT_EMOJI = {
    "CFB": "🏈",
    "GOLF": "⛳",
    "LOL": "🎮",
    "MLB": "⚾",
    "MMA": "🥊",
    "NAS": "🏎️",
    "NBA": "🏀",
    "NFL": "🏈",
    "NFLAfternoon": "🏈",
    "NFLShowdown": "🏈",
    "NHL": "🏒",
    "PGAMain": "⛳",
    "PGAShowdown": "⛳",
    "PGAWeekend": "⛳",
    "SOC": "⚽",
    "TEN": "🎾",
    "USFL": "🏈",
    "XFL": "🏈",
}


def _is_notifications_enabled() -> bool:
    return DISCORD_NOTIFICATIONS_ENABLED.strip().lower() not in {"0", "false", "no"}


def _sport_choices() -> Mapping[str, type[Sport]]:
    return get_sport_choices()


def _build_discord_sender() -> DiscordRest | None:
    """Build the Discord sender from credentials alone.

    Whether notifications are *enabled* is a separate, explicit decision
    (`_is_notifications_enabled`) injected into the processor; a sender may be
    wired yet held idle by a disabled run.
    """
    token = os.getenv("DISCORD_BOT_TOKEN")
    channel_id_raw = os.getenv("DISCORD_CHANNEL_ID")
    if not token or not channel_id_raw:
        logger.warning("DISCORD_BOT_TOKEN or DISCORD_CHANNEL_ID not set; notifications disabled.")
        return None
    try:
        channel_id = int(channel_id_raw)
    except ValueError:
        logger.warning("DISCORD_CHANNEL_ID is not a valid integer: %s", channel_id_raw)
        return None
    return DiscordRest(token, channel_id)


def _load_sheet_gid_map() -> dict[str, int]:
    if not SHEET_GIDS_FILE:
        return {}
    path = Path(SHEET_GIDS_FILE)
    if not path.is_absolute():
        path = repo_file(SHEET_GIDS_FILE)
    if not path.is_file():
        return {}
    try:
        data = yaml.safe_load(path.read_text()) or {}
    except Exception:
        logger.warning("Failed to load sheet gid map from %s", path)
        return {}
    if not isinstance(data, dict):
        return {}
    gids: dict[str, int] = {}
    for key, value in data.items():
        if isinstance(key, str) and isinstance(value, int):
            gids[key] = value
    return gids


SHEET_GID_MAP: dict[str, int] = {}


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


def _load_warning_schedule_map() -> dict[str, list[int]]:
    """Load per-sport warning schedules from YAML."""
    schedule_path = os.getenv(WARNING_SCHEDULE_FILE_ENV, DEFAULT_WARNING_SCHEDULE_FILE)
    path = Path(schedule_path)
    if not path.is_absolute():
        path = repo_file(schedule_path)
    if not path.is_file():
        return {"default": _DEFAULT_WARNING_SCHEDULE}
    try:
        data = yaml.safe_load(path.read_text()) or {}
    except Exception:
        logger.warning("Failed to load warning schedules from %s", path)
        return {"default": _DEFAULT_WARNING_SCHEDULE}
    if not isinstance(data, dict):
        logger.warning("Warning schedule file at %s did not contain a dict.", path)
        return {"default": _DEFAULT_WARNING_SCHEDULE}
    schedules: dict[str, list[int]] = {}
    for key, value in data.items():
        if not isinstance(key, str) or not key:
            logger.warning("Ignoring invalid warning schedule key: %s", key)
            continue
        normalized = _normalize_warning_schedule(value, key=key)
        if normalized:
            schedules[key.lower()] = normalized
    if "default" not in schedules:
        schedules["default"] = _DEFAULT_WARNING_SCHEDULE
    return schedules


WARNING_SCHEDULES: dict[str, list[int]] = {}


def _init_runtime() -> None:
    """Initialize settings and configuration-derived values for one run."""
    global DISCORD_NOTIFICATIONS_ENABLED
    global SPREADSHEET_ID
    global SHEET_GIDS_FILE
    global CONTEST_WARNING_MINUTES
    global _DEFAULT_WARNING_SCHEDULE
    global SHEET_GID_MAP
    global WARNING_SCHEDULES

    load_and_apply_settings()
    DISCORD_NOTIFICATIONS_ENABLED = os.getenv("DISCORD_NOTIFICATIONS_ENABLED", "true")
    SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")
    SHEET_GIDS_FILE = os.getenv("SHEET_GIDS_FILE", str(repo_file("sheet_gids.yaml")))
    CONTEST_WARNING_MINUTES = int(os.getenv("CONTEST_WARNING_MINUTES", "25"))
    _DEFAULT_WARNING_SCHEDULE = [CONTEST_WARNING_MINUTES]
    SHEET_GID_MAP = _load_sheet_gid_map()
    WARNING_SCHEDULES = _load_warning_schedule_map()
    configure_logging()


def _load_vips() -> list[str]:
    path = repo_file("vips.yaml")
    if not path.is_file():
        return []
    try:
        data = yaml.safe_load(path.read_text()) or []
    except Exception:
        logger.warning("failed to load vips.yaml from %s", path)
        return []
    if not isinstance(data, list):
        return []
    vips: list[str] = []
    for item in data:
        name = str(item).strip()
        if name:
            vips.append(name)
    return vips


def _contests_db_path() -> str:
    return str(state.contests_db_path())


class _UnavailableContestResults:
    """A `ContestResultsPort` used when the DraftKings client cannot be built.

    Every read raises, so `CompletionProcessor` degrades exactly as the original
    per-call ``DraftKings()`` construction did: contest-state reads return
    ``None`` and soft-finish evaluation is skipped, while presence stays absent.
    """

    def get_contest_detail(self, dk_id: int, timeout: int | None = None) -> dict[str, Any]:
        raise RuntimeError("DraftKings client unavailable")

    def get_contest_entrants_page(
        self,
        contest_id: int,
        page_no: int,
        timeout: int | None = None,
        session: "requests.Session | None" = None,
    ) -> str:
        raise RuntimeError("DraftKings client unavailable")

    def get_leaderboard(
        self,
        contest_id: int,
        timeout: int | None = None,
        session: "requests.Session | None" = None,
    ) -> dict[str, Any]:
        raise RuntimeError("DraftKings client unavailable")


def _build_completion_processor(conn) -> CompletionProcessor:
    """Wire the completion workflow's collaborators for one run."""
    notifications_enabled = _is_notifications_enabled()
    sender = _build_discord_sender()
    # Presence and VIP suppression only matter for announcements, which the
    # explicit `notifications_enabled` gate authorizes — resolve them by that
    # flag, not by whether a sender happens to be wired.
    vips = _load_vips() if notifications_enabled else []

    try:
        dk_client: DraftKings | None = DraftKings()
    except Exception:
        logger.warning(
            "VIP presence checks disabled; DraftKings client initialization failed",
            exc_info=True,
        )
        dk_client = None

    results = dk_client if dk_client is not None else _UnavailableContestResults()
    presence = (
        VipPresence(dk_client, NotificationStore(conn)) if (notifications_enabled and dk_client is not None) else None
    )

    config = CompletionProcessorConfig(
        sport_choices=_sport_choices(),
        warning_schedules=WARNING_SCHEDULES,
        default_warning_schedule=_DEFAULT_WARNING_SCHEDULE,
        sport_emoji=SPORT_EMOJI,
        spreadsheet_id=SPREADSHEET_ID,
        sheet_gid_map=SHEET_GID_MAP,
        vips=vips,
        notifications_enabled=notifications_enabled,
    )

    return CompletionProcessor(
        contest_db=ContestDatabase.from_connection(conn),
        results=results,
        presence=presence,
        bonus_sender=sender,
        config=config,
    )


def check_contests_for_completion(conn) -> None:
    """Advance each contest's completion state and announce its milestones."""
    _build_completion_processor(conn).run(conn)


def _build_parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(description="Update contest completion state and send contest status notifications.")


def main(argv: list[str] | None = None):
    _init_runtime()
    argv_list = list(argv) if argv is not None else []
    _build_parser().parse_args(argv_list)
    try:
        contests.init_schema(state.contests_db_path())
        conn = sqlite3.connect(_contests_db_path())
        check_contests_for_completion(conn)
    except sqlite3.Error as sql_error:
        logger.error(f"SQLite error: {sql_error}")
    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}")


if __name__ == "__main__":
    main()
