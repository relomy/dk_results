"""Serialization helpers for snapshot schema v3."""

from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Any

from dk_results.services.snapshot_exporter import to_stable_json


def _to_rfc3339_utc_seconds(value: str) -> str:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    parsed_utc = parsed.astimezone(timezone.utc).replace(microsecond=0)
    return parsed_utc.strftime("%Y-%m-%dT%H:%M:%SZ")


def serialize_payload(
    payload: dict[str, Any],
    *,
    generated_at: str | None = None,
    require_generated_at: bool = False,
) -> str:
    """Return stable JSON payload text with normalized generated_at semantics."""

    normalized = copy.deepcopy(payload)
    chosen_generated_at = generated_at or normalized.get("generated_at")
    if not chosen_generated_at and require_generated_at:
        raise ValueError("generated_at is required when deterministic serialization is enabled")
    if chosen_generated_at:
        normalized["generated_at"] = _to_rfc3339_utc_seconds(str(chosen_generated_at))
    return to_stable_json(normalized)

