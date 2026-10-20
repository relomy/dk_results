"""Validation helpers for snapshot schema v3.

``validate_v3_envelope`` is the blocking check: it runs the shape checks (``validate_shape``) and the
metrics checks (``validate_metrics``) over the envelope. ``collect_presence_warnings`` is the non-blocking
one; it lives in ``presence_rules`` and is re-exported here with ``PresenceRule`` and ``PresenceWarningRow``.
"""

from __future__ import annotations

from typing import Any

from dk_results.services.snapshot_v3.contracts import SCHEMA_VERSION, validate_single_contest
from dk_results.services.snapshot_v3.presence_rules import (
    PresenceRule as PresenceRule,  # re-exported: public names from the original path
)
from dk_results.services.snapshot_v3.presence_rules import (
    PresenceWarningRow as PresenceWarningRow,
)
from dk_results.services.snapshot_v3.presence_rules import (
    collect_presence_warnings as collect_presence_warnings,
)
from dk_results.services.snapshot_v3.validate_metrics import _validate_contest_metrics
from dk_results.services.snapshot_v3.validate_shape import (
    _validate_contest_id_coherence,
    _validate_contest_required_fields,
    _validate_section_rows,
    _validate_sport_payload,
    _validate_train_cluster_references,
    _validate_vip_lineups,
)
from dk_results.services.snapshot_v3.validate_values import _is_valid_timestamp


def validate_v3_envelope(payload: dict[str, Any]) -> list[str]:
    violations: list[str] = []

    if payload.get("schema_version") != SCHEMA_VERSION:
        violations.append("schema_version must equal 3")

    snapshot_at = payload.get("snapshot_at")
    if snapshot_at is None:
        violations.append("snapshot_at is required")
    elif not _is_valid_timestamp(snapshot_at):
        violations.append("snapshot_at must be a valid ISO timestamp")

    generated_at = payload.get("generated_at")
    if generated_at is None:
        violations.append("generated_at is required")
    elif not _is_valid_timestamp(generated_at):
        violations.append("generated_at must be a valid ISO timestamp")

    sports = payload.get("sports")
    if not isinstance(sports, dict):
        violations.append("sports must be an object")
        return violations
    if not sports:
        violations.append("sports must contain at least one sport payload")
        return violations

    for sport, sport_payload_raw in sports.items():
        violations.extend(_validate_sport_entry(str(sport), sport_payload_raw))

    return violations


def _validate_sport_entry(sport: str, sport_payload_raw: Any) -> list[str]:
    if not isinstance(sport_payload_raw, dict):
        return [f"sports.{sport} must be an object"]
    sport_payload = sport_payload_raw
    violations = _validate_sport_payload(sport, sport_payload)
    single_contest_violations = validate_single_contest(sport_payload)
    if single_contest_violations:
        return violations + [
            message.replace("sport_payload.", f"sports.{sport}.") for message in single_contest_violations
        ]
    contest = sport_payload.get("contests", [])[0]
    if not isinstance(contest, dict):
        return violations + [f"sports.{sport}.contests[0] must be an object"]
    violations.extend(_validate_contest_required_fields(sport, contest))
    violations.extend(_validate_section_rows(sport, contest))
    violations.extend(_validate_vip_lineups(sport, contest))
    violations.extend(_validate_contest_id_coherence(sport, contest))
    violations.extend(_validate_train_cluster_references(sport, contest))
    violations.extend(_validate_primary_coherence(sport, sport_payload, contest))
    violations.extend(_validate_contest_metrics(sport, sport_payload, contest))
    return violations


def _validate_primary_coherence(sport: str, sport_payload: dict[str, Any], contest: dict[str, Any]) -> list[str]:
    primary = sport_payload.get("primary_contest")
    if not isinstance(primary, dict):
        return [f"sports.{sport}.primary_contest is required"]
    violations = []
    for field in ("contest_id", "contest_key"):
        if str(primary.get(field) or "") != str(contest.get(field) or ""):
            violations.append(f"sports.{sport}.primary_contest.{field} must match contests[0].{field}")
    return violations
