"""Snapshot feed entry point (externally scheduled).

One command that builds, publishes, and loads a multi-sport snapshot into the
dashboard's object store. Runs on the existing scheduler; keeps no local state.

    uv run python snapshot_feed.py

Sports default to every supported sport; the database decides which have live
contests. R2 credentials come from the environment
(``R2_ACCOUNT_ID``, ``R2_ACCESS_KEY_ID``, ``R2_SECRET_ACCESS_KEY``) and the
bucket name from ``R2_BUCKET``.
"""

from __future__ import annotations

import argparse
import logging
from collections.abc import Sequence

from dk_results.cli.db_main import build_live_snapshot
from dk_results.config import load_and_apply_settings
from dk_results.domain.sport import get_sport_choices
from dk_results.feed.pipeline import run_feed
from dk_results.feed.r2 import R2ObjectStore
from dk_results.logging import configure_logging
from dk_results.services.snapshot_v3.constants import DEFAULT_STANDINGS_LIMIT

logger = logging.getLogger(__name__)

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover

    def load_dotenv(*_args, **_kwargs):
        return False


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="snapshot_feed.py")
    choices = get_sport_choices()
    parser.add_argument(
        "-s",
        "--sport",
        choices=choices,
        nargs="+",
        help="Sports to cover. Defaults to every supported sport.",
    )
    parser.add_argument(
        "--standings-limit",
        type=int,
        default=DEFAULT_STANDINGS_LIMIT,
        help="Standings row limit for the snapshot envelope.",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Increase verbosity")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    load_dotenv()
    load_and_apply_settings()

    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    configure_logging(level_override="DEBUG" if args.verbose else None)

    sport_names = list(args.sport) if args.sport else list(get_sport_choices())

    snapshot = build_live_snapshot(sport_names, standings_limit=args.standings_limit)
    if snapshot is None:
        logger.info("feed skipped: no live contests selected; latest pointer left intact")
        return 0

    store = R2ObjectStore.from_env()
    result = run_feed(snapshot, store)
    logger.info("feed complete uploaded keys=%s", ",".join(result.uploaded_keys))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
