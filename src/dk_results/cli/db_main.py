import argparse
import datetime
import logging
import os
import pathlib
from typing import Any
from zoneinfo import ZoneInfo

from dfs_common import state
from dfs_common.discord import WebhookSender

from dk_results.classes.contestdatabase import ContestDatabase
from dk_results.classes.draftkings import Draftkings
from dk_results.classes.sheets_service import build_dfs_sheet_service
from dk_results.classes.sport import Sport
from dk_results.config import load_and_apply_settings
from dk_results.logging import configure_logging
from dk_results.paths import repo_file
from dk_results.services.snapshot_exporter import (
    DEFAULT_STANDINGS_LIMIT,
    build_snapshot,
    normalize_snapshot_for_output,
    to_stable_json,
    to_utc_iso,
)
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
    generated_at = to_utc_iso(datetime.datetime.now(datetime.timezone.utc))
    sports: dict[str, Any] = {}
    for sport_name in sorted(selected_contests):
        contest_id = selected_contests[sport_name]
        snapshot = build_snapshot(
            sport=sport_name,
            contest_id=contest_id,
            standings_limit=standings_limit,
        )
        sports[sport_name.lower()] = normalize_snapshot_for_output(snapshot)

    return {
        "schema_version": 2,
        "snapshot_at": generated_at,
        "generated_at": generated_at,
        "sports": sports,
    }


def write_snapshot_payload(path: pathlib.Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(to_stable_json(payload), encoding="utf-8")


def main() -> None:
    """
    Use database and update Google Sheet with contest standings from DraftKings.
    """
    load_dotenv()
    load_and_apply_settings()

    parser = argparse.ArgumentParser()
    sportz: list[SportType] = Sport.__subclasses__()
    choices: dict[str, SportType] = {sport.name: sport for sport in sportz}
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

    processor = SportProcessor(
        contest_db=ContestDatabase(str(state.contests_db_path())),
        dk=Draftkings(),
        sheet_factory=lambda sport: build_dfs_sheet_service(sport),
        bonus_sender=_build_bonus_sender(),
        config=SportProcessorConfig(
            salary_dir=SALARY_DIR,
            contest_dir=CONTEST_DIR,
            cookies_file=COOKIES_FILE,
            write_optimal_lineup=args.nolineups,
        ),
        now=datetime.datetime.now(ZoneInfo("America/New_York")),
        vips=load_vips(),
    )

    selected_contests: dict[str, int] = {}
    for sport_name in args.sport:
        try:
            contest_id = processor.run(sport_name, choices[sport_name])
            selected_contests[sport_name] = contest_id
        except (NoLiveContestError, StandingsUnavailableError, StandsParseError):
            continue

    if args.snapshot_out:
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
