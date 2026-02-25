"""End-to-end snapshot v3 envelope orchestration."""

from __future__ import annotations

import datetime
from typing import Any

from dk_results.services.snapshot_exporter import DEFAULT_STANDINGS_LIMIT, to_utc_iso
from dk_results.services.snapshot_v3.builder import build_sport_payload
from dk_results.services.snapshot_v3.collector import collect_raw_bundle
from dk_results.services.snapshot_v3.contracts import SCHEMA_VERSION
from dk_results.services.snapshot_v3.derive import (
    derive_avg_salary_per_player_remaining,
    derive_distance_to_cash,
    derive_threat,
)
from dk_results.services.snapshot_v3.serialize import normalize_rfc3339_utc_seconds
from dk_results.services.snapshot_v3.validate import validate_v3_envelope


def _resolved_generated_at(generated_at: str | None) -> str:
    if generated_at:
        return normalize_rfc3339_utc_seconds(generated_at)
    fallback = to_utc_iso(datetime.datetime.now(datetime.timezone.utc))
    if fallback is None:
        return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")
    return fallback


def _build_single_sport_payload(
    *,
    sport: str,
    contest_id: int | None,
    standings_limit: int,
    generated_at: str,
) -> dict[str, Any]:
    raw_bundle = collect_raw_bundle(
        sport=sport,
        contest_id=contest_id,
        standings_limit=standings_limit,
    )
    derived = {
        "avg_salary_per_player_remaining": derive_avg_salary_per_player_remaining(raw_bundle),
        "distance_to_cash": derive_distance_to_cash(raw_bundle),
        "threat": derive_threat(raw_bundle),
    }
    return build_sport_payload(raw_bundle, derived=derived, generated_at=generated_at)


def build_snapshot_v3_envelope(
    selected_contests: dict[str, int | None],
    *,
    standings_limit: int = DEFAULT_STANDINGS_LIMIT,
    generated_at: str | None = None,
) -> dict[str, Any]:
    resolved_generated_at = _resolved_generated_at(generated_at)
    sports: dict[str, Any] = {}

    for sport_name in sorted(selected_contests):
        contest_id = selected_contests[sport_name]
        sports[sport_name.lower()] = _build_single_sport_payload(
            sport=sport_name,
            contest_id=contest_id,
            standings_limit=standings_limit,
            generated_at=resolved_generated_at,
        )

    envelope = {
        "schema_version": SCHEMA_VERSION,
        "snapshot_at": resolved_generated_at,
        "generated_at": resolved_generated_at,
        "sports": sports,
    }

    violations = validate_v3_envelope(envelope)
    if violations:
        joined = ",".join(violations)
        raise ValueError(f"Snapshot v3 validation failed: {joined}")

    return envelope
