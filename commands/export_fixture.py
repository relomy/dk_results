import logging
import pathlib
from typing import Any

from services.snapshot_exporter import (
    DEFAULT_STANDINGS_LIMIT,
    build_dashboard_envelope,
    build_snapshot,
    configure_runtime,
    normalize_snapshot_for_output,
    normalize_sport_name,
    to_stable_json,
    validate_canonical_snapshot,
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
    envelope = build_dashboard_envelope({sport: snapshot})
    violations = validate_canonical_snapshot(envelope)
    if violations:
        logger.error("canonical contract violations=%s", ",".join(violations))
        raise ValueError("Canonical snapshot validation failed")
    json_text = to_stable_json(envelope)
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


def _parse_bundle_item(raw_item: str) -> tuple[str, int]:
    value = str(raw_item or "").strip()
    if ":" not in value:
        raise ValueError(f"Invalid bundle item '{raw_item}'. Expected SPORT:CONTEST_ID.")
    raw_sport, raw_contest_id = value.split(":", 1)
    sport = normalize_sport_name(raw_sport)
    try:
        contest_id = int(raw_contest_id)
    except ValueError as exc:
        raise ValueError(
            f"Invalid contest id in bundle item '{raw_item}'. Expected integer id."
        ) from exc
    return sport, contest_id


def run_export_bundle(args: Any) -> int:
    logging.getLogger("Draftkings").setLevel(logging.INFO)
    logging.getLogger("classes.results").setLevel(logging.INFO)
    configure_runtime()
    standings_limit = int(args.standings_limit) if args.standings_limit else DEFAULT_STANDINGS_LIMIT

    items = list(getattr(args, "item", []) or [])
    if not items:
        raise ValueError("At least one --item SPORT:CONTEST_ID is required for bundle export.")

    parsed_items = [_parse_bundle_item(item) for item in items]
    sports: dict[str, Any] = {}
    for sport, contest_id in parsed_items:
        snapshot = build_snapshot(
            sport=sport,
            contest_id=contest_id,
            standings_limit=standings_limit,
        )
        sports[sport] = snapshot
    payload = build_dashboard_envelope(sports)
    violations = validate_canonical_snapshot(payload)
    if violations:
        logger.error("canonical contract violations=%s", ",".join(violations))
        raise ValueError("Canonical snapshot validation failed")
    out_path = pathlib.Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(to_stable_json(payload), encoding="utf-8")

    logger.info("bundle candidate count=%d", len(parsed_items))
    logger.info("bundle output path=%s", out_path)
    return 0
