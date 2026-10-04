"""Export the snapshot contract's JSON Schema to its committed, stable path.

    uv run python export_snapshot_schema.py

Writes ``contract/snapshot.schema.json`` from the pydantic contract models in
``dk_results.services.snapshot_v3.models``. The file is generated: re-run this
command after changing the models and commit the result; never edit it by hand.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from dk_results.paths import repo_file
from dk_results.services.json_stable import to_stable_json
from dk_results.services.snapshot_v3.models.envelope import snapshot_json_schema

SCHEMA_PATH = ("contract", "snapshot.schema.json")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="export_snapshot_schema.py")
    parser.add_argument(
        "--out",
        type=Path,
        default=repo_file(*SCHEMA_PATH),
        help="Output path (default: the committed contract/snapshot.schema.json).",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    out: Path = args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(to_stable_json(snapshot_json_schema()), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
