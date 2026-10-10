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


def build_default_processor(
    *, write_optimal_lineup: bool = True, contest_db: ContestDatabase | None = None
) -> SportProcessor:
    """Construct the production SportProcessor with its real ports and config."""
    return SportProcessor(
        contest_db=contest_db if contest_db is not None else ContestDatabase(str(state.contests_db_path())),
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


def _log_contest_selection(selected: Mapping[str, int], idle: list[str], *, requested: int) -> None:
    logger.info(
        "contest_selection selected=%s no_live=%d requested=%d",
        ",".join(selected) or "none",
        len(idle),
        requested,
    )
    if idle:
        logger.debug("contest_selection idle=%s", ",".join(idle))


def _partition_live_contests(
    processor: SportProcessor,
    sport_names: list[str],
    choices: Mapping[str, SportType],
) -> tuple[dict[str, int], list[str]]:
    """Run each sport through the processor; return (selected, idle) sports.

    Only a sport with no live contest is idle. A sport whose standings were
    unavailable/unparseable is neither selected nor idle, so one bad sport
    degrades that sport only.
    """
    selected: dict[str, int] = {}
    idle: list[str] = []
    for sport_name in sport_names:
        try:
            selected[sport_name] = processor.run(sport_name, choices[sport_name])
        except NoLiveContestError:
            idle.append(sport_name)
        except (StandingsUnavailableError, StandsParseError):
            continue
    return selected, idle


def select_live_contests(
    processor: SportProcessor,
    sport_names: list[str],
    choices: Mapping[str, SportType],
) -> dict[str, int]:
    """Run each sport through the processor; the database decides which are live.

    A sport with no live contest (or unavailable/unparseable standings) is
    skipped, so one bad sport degrades that sport only. Idle sports are the
    normal case, so they are reported in one summary line (and one DEBUG line
    naming them) rather than logged individually.
    """
    selected, idle = _partition_live_contests(processor, sport_names, choices)
    _log_contest_selection(selected, idle, requested=len(sport_names))
    return selected


def _recently_completed_selection(
    contest_db: ContestDatabase,
    idle: list[str],
    choices: Mapping[str, SportType],
    now: datetime.datetime | None,
) -> dict[str, int]:
    """Map each idle sport to its primary contest completed inside the completion window."""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    filled: dict[str, int] = {}
    for sport_name in idle:
        sport_cls = choices[sport_name]
        row = contest_db.get_recently_completed_contest(
            sport_cls.name, sport_cls.sheet_min_entry_fee, sport_cls.keyword, now=now
        )
        if row:
            filled[sport_name] = row[0]
    if filled:
        logger.info("contest_selection completed_in_window=%s", ",".join(filled))
    return filled


def build_live_snapshot(
    sport_names: list[str],
    *,
    standings_limit: int = DEFAULT_STANDINGS_LIMIT,
    processor: SportProcessor | None = None,
    contest_db: ContestDatabase | None = None,
    now: datetime.datetime | None = None,
) -> dict[str, Any] | None:
    """Select live contests via the DB-driven processor and build a multi-sport
    snapshot envelope. Returns ``None`` when no contest was selected.

    A sport with no live contest is filled from its primary ``COMPLETED``
    contest still inside the completion window (ADR-0015); a live contest in
    the same sport always wins. ``now`` (tz-aware) exists for testing.

    This is the build step the snapshot feed reuses; it does not reimplement
    snapshot shaping (``build_snapshot_payload`` owns that).
    """
    choices = get_sport_choices()
    contest_db = contest_db or ContestDatabase(str(state.contests_db_path()))
    processor = processor if processor is not None else build_default_processor(contest_db=contest_db)
    selected, idle = _partition_live_contests(processor, sport_names, choices)
    _log_contest_selection(selected, idle, requested=len(sport_names))
    selected = {**selected, **_recently_completed_selection(contest_db, idle, choices, now)}
    if not selected:
        return None
    return build_snapshot_payload(selected, standings_limit=standings_limit)


def main() -> None:
    """
    Use database and update Google Sheet with contest standings from DraftKings.
    """
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
