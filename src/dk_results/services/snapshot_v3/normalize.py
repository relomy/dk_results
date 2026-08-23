"""Shared normalization helpers for snapshot v3."""

from __future__ import annotations

import datetime
import re
from typing import Any
from zoneinfo import ZoneInfo


def to_utc_iso(value: datetime.datetime | str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        text = text.replace("Z", "+00:00")
        try:
            value = datetime.datetime.fromisoformat(text)
        except ValueError:
            return None

    if value.tzinfo is None:
        value = value.replace(tzinfo=ZoneInfo("America/New_York"))
    value = value.astimezone(datetime.timezone.utc)
    return value.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def to_float(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip().replace("$", "").replace(",", "")
        if not text:
            return None
        try:
            return float(text)
        except ValueError:
            return None
    return None


def to_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if value.is_integer():
            return int(value)
        return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return int(text)
        except ValueError:
            return None
    return None


def normalize_name(value: Any) -> str:
    return str(value or "").strip().lower()


def slug(value: Any) -> str:
    normalized = normalize_name(value)
    if not normalized:
        return ""
    return re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")


def is_live_from_slot(slot: dict[str, Any]) -> bool:
    raw_is_live = slot.get("is_live")
    if isinstance(raw_is_live, bool):
        return raw_is_live

    for key in ("time_remaining_minutes", "timeRemaining", "timeStatus", "time_remaining_display"):
        minutes = to_float(slot.get(key))
        if minutes is not None:
            return minutes > 0

    text_candidates = [
        slot.get("timeStatus"),
        slot.get("time_remaining_display"),
        slot.get("timeRemaining"),
        slot.get("game_status"),
        slot.get("status"),
    ]
    live_markers = ("in progress", "live", "q1", "q2", "q3", "q4", "ot", "thru", "hole")
    final_markers = ("final", "complete", "completed", "locked", "postponed", "canceled", "cancelled")
    for raw_text in text_candidates:
        status_text = str(raw_text or "").strip().lower()
        if not status_text or status_text in {"-", "--"}:
            continue
        if any(marker in status_text for marker in final_markers):
            return False
        if any(marker in status_text for marker in live_markers):
            return True
        if ":" in status_text:
            return True
    return False
