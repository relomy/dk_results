import argparse
import logging
import os
import sqlite3
from collections.abc import Mapping
from typing import Any

import requests
import yaml
from dfs_common import contests, state

from dk_results.bot.discord_rest import DiscordRest
from dk_results.completion_processor import CompletionProcessor, CompletionProcessorConfig
from dk_results.config import RuntimeSettings, load_runtime_settings
from dk_results.discord_announcements import SPORT_EMOJI
from dk_results.domain.sport import Sport, get_sport_choices
from dk_results.draftkings import DraftKings
from dk_results.logging import configure_logging
from dk_results.notifications.vip_presence import VipPresence
from dk_results.paths import repo_file
from dk_results.persistence.contestdatabase import ContestDatabase
from dk_results.persistence.notification_store import NotificationStore

logger = logging.getLogger(__name__)


def _sport_choices() -> Mapping[str, type[Sport]]:
    return get_sport_choices()


def _build_discord_sender() -> DiscordRest | None:
    """Build the Discord sender from credentials alone.

    Whether notifications are *enabled* is a separate, explicit decision
    (`RuntimeSettings.discord_notifications_enabled`) injected into the
    processor; a sender may be wired yet held idle by a disabled run.
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


def _build_completion_processor(conn, settings: RuntimeSettings) -> CompletionProcessor:
    """Wire the completion workflow's collaborators for one run."""
    notifications_enabled = settings.discord_notifications_enabled
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
        warning_schedules=settings.warning_schedules,
        default_warning_schedule=settings.default_warning_schedule,
        sport_emoji=SPORT_EMOJI,
        spreadsheet_id=settings.spreadsheet_id,
        sheet_gid_map=settings.sheet_gid_map,
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


def check_contests_for_completion(conn, settings: RuntimeSettings) -> None:
    """Advance each contest's completion state and announce its milestones."""
    _build_completion_processor(conn, settings).run(conn)


def _build_parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(description="Update contest completion state and send contest status notifications.")


def main(argv: list[str] | None = None):
    settings = load_runtime_settings()
    configure_logging()
    argv_list = list(argv) if argv is not None else []
    _build_parser().parse_args(argv_list)
    try:
        contests.init_schema(state.contests_db_path())
        conn = sqlite3.connect(_contests_db_path())
        check_contests_for_completion(conn, settings)
    except sqlite3.Error as sql_error:
        logger.error(f"SQLite error: {sql_error}")
    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}")


if __name__ == "__main__":
    main()
