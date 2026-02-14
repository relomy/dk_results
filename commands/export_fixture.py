import logging
import pathlib
from typing import Any

from services.snapshot_exporter import (
    DEFAULT_STANDINGS_LIMIT,
    build_snapshot,
    configure_runtime,
    normalize_snapshot_for_output,
    normalize_sport_name,
    snapshot_to_json,
)

logger = logging.getLogger(__name__)

def _default_output_path(snapshot: dict[str, Any], sport: str) -> pathlib.Path:
    selected_id = str(snapshot.get("selection", {}).get("selected_contest_id") or "unknown")
    return pathlib.Path("fixtures") / f"{sport.lower()}-{selected_id}-fixture.json"


def run_export_fixture(args: Any) -> int:
    logging.getLogger("Draftkings").setLevel(logging.INFO)
    logging.getLogger("classes.results").setLevel(logging.INFO)
    configure_runtime()
    sport = normalize_sport_name(args.sport)
    contest_id = int(args.contest_id) if args.contest_id is not None else None
    standings_limit = int(args.standings_limit) if args.standings_limit else DEFAULT_STANDINGS_LIMIT

    snapshot = build_snapshot(
        sport=sport,
        contest_id=contest_id,
        standings_limit=standings_limit,
    )
    json_text = snapshot_to_json(snapshot)
    out_path = pathlib.Path(args.out) if getattr(args, "out", None) else _default_output_path(snapshot, sport)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json_text, encoding="utf-8")

    selected_id = snapshot.get("selection", {}).get("selected_contest_id")
    candidates = snapshot.get("candidates", [])
    missing = snapshot.get("metadata", {}).get("missing_fields", [])
    warning_count = len(normalize_snapshot_for_output(snapshot)["metadata"]["warnings"])

    logger.info("selected contest id=%s", selected_id)
    logger.info("candidate count=%d", len(candidates))
    logger.info("missing fields=%s", ",".join(missing))
    logger.info("warning count=%d", warning_count)
    logger.info("output path=%s", out_path)
    return 0
