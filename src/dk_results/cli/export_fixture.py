import argparse
import sys
from typing import Sequence

from dk_results.commands.export_fixture import run_export_bundle, run_export_fixture, run_publish_snapshot
from dk_results.services.snapshot_exporter import DEFAULT_STANDINGS_LIMIT


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="export_fixture.py")
    parser.add_argument("--sport", required=True, help="Sport name, e.g. NBA")
    parser.add_argument("--contest-id", type=int, help="Optional explicit contest id")
    parser.add_argument("--out", help="Output JSON fixture path")
    parser.add_argument(
        "--standings-limit",
        type=int,
        default=DEFAULT_STANDINGS_LIMIT,
        help="Maximum number of standings rows to include",
    )
    return parser


def build_bundle_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="export_fixture.py bundle")
    parser.add_argument(
        "--item",
        action="append",
        required=True,
        help="Repeatable item in the format SPORT:CONTEST_ID, e.g. NBA:123456789",
    )
    parser.add_argument("--out", required=True, help="Output JSON bundle path")
    parser.add_argument(
        "--standings-limit",
        type=int,
        default=DEFAULT_STANDINGS_LIMIT,
        help="Maximum number of standings rows to include per sport",
    )
    return parser


def build_publish_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="export_fixture.py publish")
    parser.add_argument(
        "--snapshot",
        required=True,
        help="Path to an existing snapshot envelope JSON file.",
    )
    parser.add_argument(
        "--root",
        required=True,
        help="Root directory for latest.json and manifest/ outputs.",
    )
    parser.add_argument(
        "--snapshot-path",
        help=(
            "Optional API-visible snapshot path for latest/manifest entry, "
            "for example snapshots/live-2026-02-15T01-30-00Z.json."
        ),
    )
    parser.add_argument(
        "--latest-out",
        help="Optional explicit latest.json output path. Defaults to <root>/latest.json.",
    )
    parser.add_argument(
        "--manifest-dir",
        help="Optional explicit manifest directory. Defaults to <root>/manifest.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    argv_list = list(argv) if argv is not None else sys.argv[1:]
    if argv_list and argv_list[0] == "bundle":
        parser = build_bundle_parser()
        args = parser.parse_args(argv_list[1:])
        return int(run_export_bundle(args) or 0)
    if argv_list and argv_list[0] == "publish":
        parser = build_publish_parser()
        args = parser.parse_args(argv_list[1:])
        return int(run_publish_snapshot(args) or 0)
    parser = build_parser()
    args = parser.parse_args(argv_list)
    return int(run_export_fixture(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
