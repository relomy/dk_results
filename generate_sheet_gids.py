import os
from pathlib import Path

import yaml

from classes.dfssheet import fetch_sheet_gids


def main() -> None:
    spreadsheet_id = os.getenv("SPREADSHEET_ID")
    if not spreadsheet_id:
        raise RuntimeError("SPREADSHEET_ID is not set.")

    gids = fetch_sheet_gids(spreadsheet_id)
    output_path = Path(__file__).with_name("sheet_gids.yaml")
    output_path.write_text(yaml.safe_dump(gids, sort_keys=True), encoding="utf-8")
    print(f"Wrote {len(gids)} sheet gids to {output_path}")


if __name__ == "__main__":
    main()
