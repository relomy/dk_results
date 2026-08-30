import argparse
import datetime
import logging
import os
import pathlib
from collections.abc import Mapping
from typing import Any
from zoneinfo import ZoneInfo

from dfs_common import state
from dfs_common.discord import WebhookSender

from dk_results.config import load_and_apply_settings
from dk_results.domain.sport import Sport, get_sport_choices
from dk_results.draftkings import DraftKings
from dk_results.logging import configure_logging
from dk_results.paths import repo_file
from dk_results.persistence.contestdatabase import ContestDatabase
from dk_results.services.json_stable import to_stable_json
from dk_results.services.snapshot_v3.constants import DEFAULT_STANDINGS_LIMIT
from dk_results.services.snapshot_v3.pipeline import build_snapshot_v3_envelope
from dk_results.sheets.sheets_service import build_dfs_sheet_service
from dk_results.sport_processor import (
    NoLiveContestError,
    SportProcessor,
    SportProcessorConfig,
    StandingsUnavailableError,
    StandsParseError,
)
from dk_results.vip_lineups import load_vips

logger = logging.getLogger(__name__)

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover

    def load_dotenv(*_args, **_kwargs):
        return False


SportType = type[Sport]

CONTEST_DIR = str(repo_file("contests"))
SALARY_DIR = str(repo_file("salary"))
COOKIES_FILE = str(repo_file("pickled_cookies_works.txt"))


def _build_bonus_sender() -> WebhookSender | None:
    notifications_enabled = os.getenv("DISCORD_NOTIFICATIONS_ENABLED", "true").strip().lower() not in {
        "0",
        "false",
        "no",
    }
    if not notifications_enabled:
        return None
    webhook = os.getenv("DISCORD_BONUS_WEBHOOK") or os.getenv("DISCORD_WEBHOOK")
    if not webhook:
        return None
    return WebhookSender(webhook)


def build_snapshot_payload(
    selected_contests: dict[str, int],
    standings_limit: int = DEFAULT_STANDINGS_LIMIT,
) -> dict[str, Any]:
    return build_snapshot_v3_envelope(
        {sport: contest_id for sport, contest_id in selected_contests.items()},
        standings_limit=standings_limit,
    )


def write_snapshot_payload(path: pathlib.Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(to_stable_json(payload), encoding="utf-8")


def build_default_processor(*, write_optimal_lineup: bool = True) -> SportProcessor:
    """Construct the production SportProcessor with its real ports and config."""
    return SportProcessor(
        contest_db=ContestDatabase(str(state.contests_db_path())),
        dk=DraftKings(),
        sheet_factory=lambda sport: build_dfs_sheet_service(sport),
        bonus_sender=_build_bonus_sender(),
        config=SportProcessorConfig(
            salary_dir=SALARY_DIR,
            contest_dir=CONTEST_DIR,
            cookies_file=COOKIES_FILE,
            write_optimal_lineup=write_optimal_lineup,
        ),
        now=datetime.datetime.now(ZoneInfo("America/New_York")),
        vips=load_vips(),
    )


def select_live_contests(
    processor: SportProcessor,
    sport_names: list[str],
    choices: Mapping[str, SportType],
) -> dict[str, int]:
    """Run each sport through the processor; the database decides which are live.

    A sport with no live contest (or unavailable/unparseable standings) is
    skipped, so one bad sport degrades that sport only.
    """
    selected: dict[str, int] = {}
    for sport_name in sport_names:
        try:
            selected[sport_name] = processor.run(sport_name, choices[sport_name])
        except (NoLiveContestError, StandingsUnavailableError, StandsParseError):
            continue
    return selected


def build_live_snapshot(
    sport_names: list[str],
    *,
    standings_limit: int = DEFAULT_STANDINGS_LIMIT,
    processor: SportProcessor | None = None,
) -> dict[str, Any] | None:
    """Select live contests via the DB-driven processor and build a multi-sport
    snapshot envelope. Returns ``None`` when no contest was selected.

    This is the build step the snapshot feed reuses; it does not reimplement
    snapshot shaping (``build_snapshot_payload`` owns that).
    """
    choices = get_sport_choices()
    processor = processor if processor is not None else build_default_processor()
    selected = select_live_contests(processor, sport_names, choices)
    if not selected:
        return None
    return build_snapshot_payload(selected, standings_limit=standings_limit)


def main() -> None:
    """
    Use database and update Google Sheet with contest standings from DraftKings.
    """
    load_dotenv()
    load_and_apply_settings()

    parser = argparse.ArgumentParser()
    choices: Mapping[str, SportType] = get_sport_choices()
    parser.add_argument(
        "-s",
        "--sport",
        choices=choices,
        required=True,
        help="Type of contest",
        nargs="+",
    )
    parser.add_argument(
        "--nolineups",
        dest="nolineups",
        action="store_false",
        help="If true, will not print VIP lineups",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Increase verbosity")
    parser.add_argument(
        "--snapshot-out",
        help="Optional path to write a multi-sport snapshot envelope for selected contests.",
    )
    parser.add_argument(
        "--standings-limit",
        type=int,
        default=DEFAULT_STANDINGS_LIMIT,
        help="Standings row limit used for snapshot export output.",
    )
    args = parser.parse_args()
    configure_logging(level_override="DEBUG" if args.verbose else None)

    processor = build_default_processor(write_optimal_lineup=args.nolineups)
    selected_contests = select_live_contests(processor, args.sport, choices)

    if args.snapshot_out:
        if not selected_contests:
            logger.info("snapshot skipped: no contests selected; existing output preserved")
            return
        payload = build_snapshot_payload(
            selected_contests,
            standings_limit=args.standings_limit,
        )
        out_path = pathlib.Path(args.snapshot_out)
        write_snapshot_payload(out_path, payload)
        logger.info("snapshot selected_contests=%d", len(selected_contests))
        logger.info("snapshot output path=%s", out_path)


if __name__ == "__main__":
    main()
