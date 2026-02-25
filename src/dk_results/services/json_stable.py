"""Stable JSON serialization helpers shared across exporter modules."""

from __future__ import annotations

import json
from typing import Any


def to_stable_json(payload: Any) -> str:
    return (
        json.dumps(
            payload,
            sort_keys=True,
            indent=2,
            separators=(",", ":"),
            ensure_ascii=True,
        )
        + "\n"
    )

