"""Gate a PR's snapshot contract schema against its base branch's.

    uv run python check_snapshot_schema_compat.py --base BASE_SCHEMA \
        [--breaking-change-label --base-doc BASE_SCHEMA_DOC]

Prints each breaking change from the base schema to the committed
``contract/snapshot.schema.json`` and exits non-zero when there is one, unless
the PR carries the ``breaking-change`` label and every reported path is named
by an entry ``docs/SNAPSHOT_SCHEMA.md``'s Breaking changes log gained over the
base branch's copy. A base with
no schema yet (the contract's first introduction) passes. Uses only this
repository's artifacts; CI passes the base files via ``git show``.
"""

from __future__ import annotations

import argparse
import json
import re
from collections.abc import Sequence
from pathlib import Path

from dk_results.paths import repo_file
from dk_results.services.snapshot_v3.compat import BreakingChange, breaking_changes

SCHEMA_PATH = ("contract", "snapshot.schema.json")
SCHEMA_DOC_PATH = ("docs", "SNAPSHOT_SCHEMA.md")
LABEL = "breaking-change"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="check_snapshot_schema_compat.py")
    parser.add_argument("--base", type=Path, required=True, help="The base branch's exported schema.")
    parser.add_argument(
        "--current",
        type=Path,
        default=repo_file(*SCHEMA_PATH),
        help="The PR's exported schema (default: the committed contract/snapshot.schema.json).",
    )
    parser.add_argument(
        "--breaking-change-label",
        action="store_true",
        help=f"The PR carries the `{LABEL}` label: breaking changes pass if new log entries name every path.",
    )
    parser.add_argument("--base-doc", type=Path, help="The base branch's docs/SNAPSHOT_SCHEMA.md (absent: no log).")
    parser.add_argument(
        "--doc",
        type=Path,
        default=repo_file(*SCHEMA_DOC_PATH),
        help="The PR's schema document (default: docs/SNAPSHOT_SCHEMA.md).",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    if not args.base.is_file():
        print(f"Schema compatibility: no snapshot schema on the base branch ({args.base}); nothing to compare.")
        return 0
    changes = breaking_changes(_load(args.base), _load(args.current))
    if not changes:
        print("Schema compatibility: no breaking changes.")
        return 0
    _print_changes(changes)
    if not args.breaking_change_label:
        print(
            f"\nA breaking change fails by default. To ship it deliberately, label the PR `{LABEL}` "
            "and add a migration note to the Breaking changes log in docs/SNAPSHOT_SCHEMA.md."
        )
        return 1
    return _check_changes_are_logged(changes, args.base_doc, args.doc)


def _check_changes_are_logged(changes: list[BreakingChange], base_doc: Path | None, doc: Path) -> int:
    base_entries = set(breaking_change_log_entries(_read_optional(base_doc)))
    added = [entry for entry in breaking_change_log_entries(_read_optional(doc)) if entry not in base_entries]
    unlogged = sorted({change.path for change in changes if not _is_named_by(change.path, added)})
    if unlogged:
        print(f"\nThe PR is labeled `{LABEL}`, but the Breaking changes log in {doc} is missing a note for:")
        for path in unlogged:
            print(f"  - no new Breaking changes log entry names `{_display(path)}`")
        print("Add an entry naming each path above and the consumer's migration.")
        return 1
    print(f"\nLabeled `{LABEL}`; new Breaking changes log entries:")
    for entry in added:
        print(f"  - {entry}")
    return 0


BREAKING_CHANGE_LOG_HEADING = "## Breaking changes"


def breaking_change_log_entries(schema_doc: str) -> list[str]:
    """The entries (top-level bullets) of the schema document's breaking-change log.

    A bullet's indented continuation lines are joined onto it, so an entry
    compares equal however it is wrapped.
    """
    entries: list[str] = []
    in_log = False
    for line in schema_doc.splitlines():
        if line.startswith("## "):
            in_log = line.strip() == BREAKING_CHANGE_LOG_HEADING
        elif in_log:
            _collect_entry_line(entries, line)
    return entries


def _collect_entry_line(entries: list[str], line: str) -> None:
    if line.startswith("- "):
        entries.append(line[2:].strip())
    elif entries and line.startswith(" ") and line.strip():
        entries[-1] = f"{entries[-1]} {line.strip()}"


ROOT_PATH = "(root)"


def _display(path: str) -> str:
    return path or ROOT_PATH


def _is_named_by(path: str, entries: list[str]) -> bool:
    """True when an entry names the whole path, not just a longer or shorter dotted path sharing it."""
    pattern = re.compile(rf"(?<![\w.*\[\]]){re.escape(_display(path))}(?![\w*\[]|\.\w)")
    return any(pattern.search(entry) for entry in entries)


def _read_optional(path: Path | None) -> str:
    return path.read_text(encoding="utf-8") if path is not None and path.is_file() else ""


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _print_changes(changes: list[BreakingChange]) -> None:
    print(f"Schema compatibility: {len(changes)} breaking change(s):")
    for change in changes:
        detail = f" ({change.detail})" if change.detail else ""
        print(f"  {change.kind}: {change.path}{detail}")


if __name__ == "__main__":
    raise SystemExit(main())
