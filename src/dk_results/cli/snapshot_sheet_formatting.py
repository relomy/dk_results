"""CLI for dumping a readable snapshot of a Google Sheet's live formatting."""

from __future__ import annotations

import argparse

from dk_results.paths import repo_file
from dk_results.sheets.format_snapshot import fetch_raw_formatting, render_markdown, summarize_spreadsheet
from dk_results.sheets.sheets_service import make_sheet_client


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "sheets",
        nargs="+",
        help="Sheet tab titles to snapshot, e.g. NBA GOLF",
    )
    parser.add_argument(
        "--output",
        default="sheet_formatting_snapshot.md",
        help="Output markdown path (relative to repo root unless absolute)",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    client = make_sheet_client()
    raw = fetch_raw_formatting(client.service, client.spreadsheet_id, args.sheets)
    summaries = summarize_spreadsheet(raw)
    report = render_markdown(summaries)

    output_path = repo_file(args.output)
    output_path.write_text(report, encoding="utf-8")
    print(f"Wrote formatting snapshot for {', '.join(args.sheets)} to {output_path}")


if __name__ == "__main__":
    main()
