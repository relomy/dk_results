import argparse
from typing import Sequence

from commands.export_fixture import run_export_fixture
from services.snapshot_exporter import DEFAULT_STANDINGS_LIMIT


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


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(run_export_fixture(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
