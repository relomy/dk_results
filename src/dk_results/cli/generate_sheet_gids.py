from pathlib import Path

import yaml

from dk_results.classes.sheets_service import fetch_sheet_gids


def main() -> None:
    gids = fetch_sheet_gids()
    output_path = Path(__file__).with_name("sheet_gids.yaml")
    output_path.write_text(yaml.safe_dump(gids, sort_keys=True), encoding="utf-8")
    print(f"Wrote {len(gids)} sheet gids to {output_path}")


if __name__ == "__main__":
    main()
