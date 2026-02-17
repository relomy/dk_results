import logging
import pathlib
from datetime import datetime, timedelta
from typing import Any

from dk_results.services.snapshot_exporter import (
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

_MANIFEST_VERSION = 1
_VALID_SPORT_STATUS = {"ok", "stale", "error"}


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
        raise ValueError(f"Invalid contest id in bundle item '{raw_item}'. Expected integer id.") from exc
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


def _normalize_snapshot_path(path: pathlib.Path) -> pathlib.Path:
    return path.resolve()


def _resolve_snapshot_rel_path(
    snapshot_path: pathlib.Path,
    root_path: pathlib.Path,
    override: str | None,
) -> str:
    if override:
        return str(pathlib.PurePosixPath(override.strip().lstrip("/")))
    try:
        rel = snapshot_path.relative_to(root_path)
    except ValueError as exc:
        raise ValueError(
            f"Snapshot path {snapshot_path} is not inside root {root_path}. "
            "Pass --snapshot-path to set the API-visible path explicitly."
        ) from exc
    return rel.as_posix()


def _coerce_iso(value: Any, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"Snapshot payload missing required field: {field_name}")
    datetime.fromisoformat(text.replace("Z", "+00:00"))
    return text


def _build_latest_payload(
    payload: dict[str, Any],
    snapshot_rel_path: str,
    manifest_today_path: str,
) -> dict[str, Any]:
    snapshot_at = _coerce_iso(payload.get("snapshot_at"), "snapshot_at")
    generated_at = _coerce_iso(payload.get("generated_at"), "generated_at")
    available_sports = sorted(str(key) for key in (payload.get("sports") or {}).keys())
    date_utc = snapshot_at[:10]
    yesterday_utc = (datetime.fromisoformat(f"{date_utc}T00:00:00+00:00") - timedelta(days=1)).date().isoformat()
    return {
        "latest_snapshot_path": snapshot_rel_path,
        "snapshot_at": snapshot_at,
        "generated_at": generated_at,
        "available_sports": available_sports,
        "manifest_today_path": manifest_today_path,
        "manifest_yesterday_path": f"manifest/{yesterday_utc}.json",
    }


def _build_manifest_entry(
    payload: dict[str, Any],
    snapshot_rel_path: str,
    snapshot_path: pathlib.Path,
) -> dict[str, Any]:
    sports = payload.get("sports") or {}
    sports_present = sorted(str(key) for key in sports.keys())
    contest_counts_by_sport: dict[str, int] = {}
    state_counts: dict[str, int] = {}
    sports_status: dict[str, dict[str, Any]] = {}

    for sport in sports_present:
        sport_payload = sports.get(sport) or {}
        contests = sport_payload.get("contests") or []
        contest_counts_by_sport[sport] = len(contests)

        for contest in contests:
            state_raw = str((contest or {}).get("state") or "").strip().lower()
            state = state_raw if state_raw in {"upcoming", "live", "completed", "cancelled"} else "unknown"
            state_counts[state] = state_counts.get(state, 0) + 1

        status_raw = str(sport_payload.get("status") or "").strip().lower()
        status = status_raw if status_raw in _VALID_SPORT_STATUS else ("error" if sport_payload.get("error") else "ok")
        sport_status: dict[str, Any] = {
            "status": status,
            "updated_at": _coerce_iso(
                sport_payload.get("updated_at") or payload.get("generated_at"),
                f"sports.{sport}.updated_at",
            ),
        }
        error_value = sport_payload.get("error")
        if error_value not in (None, ""):
            sport_status["error"] = str(error_value)
        sports_status[sport] = sport_status

    return {
        "snapshot_at": _coerce_iso(payload.get("snapshot_at"), "snapshot_at"),
        "path": snapshot_rel_path,
        "byte_size": snapshot_path.stat().st_size,
        "sports_present": sports_present,
        "contest_counts_by_sport": contest_counts_by_sport,
        "state_counts": state_counts,
        "sports_status": sports_status,
    }


def _load_json_dict(path: pathlib.Path) -> dict[str, Any]:
    import json

    return dict(json.loads(path.read_text(encoding="utf-8")))


def run_publish_snapshot(args: Any) -> int:
    snapshot_path = _normalize_snapshot_path(pathlib.Path(args.snapshot))
    if not snapshot_path.exists():
        raise ValueError(f"Snapshot file does not exist: {snapshot_path}")

    root_path = _normalize_snapshot_path(pathlib.Path(args.root))
    snapshot_rel_path = _resolve_snapshot_rel_path(
        snapshot_path,
        root_path,
        getattr(args, "snapshot_path", None),
    )
    payload = _load_json_dict(snapshot_path)
    snapshot_at = _coerce_iso(payload.get("snapshot_at"), "snapshot_at")
    date_utc = snapshot_at[:10]

    manifest_dir = (
        _normalize_snapshot_path(pathlib.Path(args.manifest_dir))
        if getattr(args, "manifest_dir", None)
        else root_path / "manifest"
    )
    latest_out = (
        _normalize_snapshot_path(pathlib.Path(args.latest_out))
        if getattr(args, "latest_out", None)
        else root_path / "latest.json"
    )
    manifest_path = manifest_dir / f"{date_utc}.json"
    manifest_today_path = f"manifest/{date_utc}.json"

    latest_payload = _build_latest_payload(payload, snapshot_rel_path, manifest_today_path)
    latest_out.parent.mkdir(parents=True, exist_ok=True)
    latest_out.write_text(to_stable_json(latest_payload), encoding="utf-8")

    if manifest_path.exists():
        existing_manifest = _load_json_dict(manifest_path)
        snapshots = list(existing_manifest.get("snapshots") or [])
    else:
        snapshots = []

    entry = _build_manifest_entry(payload, snapshot_rel_path, snapshot_path)
    snapshots = [item for item in snapshots if str(item.get("snapshot_at")) != entry["snapshot_at"]]
    snapshots.append(entry)
    snapshots.sort(key=lambda item: str(item.get("snapshot_at") or ""), reverse=True)

    manifest_payload = {
        "manifest_version": _MANIFEST_VERSION,
        "date_utc": date_utc,
        "generated_at": _coerce_iso(payload.get("generated_at"), "generated_at"),
        "snapshots": snapshots,
    }

    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(to_stable_json(manifest_payload), encoding="utf-8")

    logger.info("snapshot publish latest path=%s", latest_out)
    logger.info("snapshot publish manifest path=%s", manifest_path)
    return 0
