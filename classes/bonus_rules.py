"""Parsing rules for DraftKings bonus opportunities from statsDescription."""

from __future__ import annotations

import re

_GOLF_TOKEN_RE = re.compile(r"(?<!\w)(\d+)\s*(EAG|BOFR|BIR3\+)(?!\w)")
_NBA_DDBL_RE = re.compile(r"\bDDbl\b")
_NBA_TDBL_RE = re.compile(r"\bTDbl\b")


def _parse_golf_bonus_counts(stats_description: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for raw_count, token in _GOLF_TOKEN_RE.findall(stats_description or ""):
        count = int(raw_count)
        if count <= 0:
            continue
        counts[token] = max(count, counts.get(token, 0))
    return counts


def _parse_nba_bonus_counts(stats_description: str) -> dict[str, int]:
    text = stats_description or ""
    counts: dict[str, int] = {}
    if _NBA_DDBL_RE.search(text):
        counts["DDbl"] = 1
    if _NBA_TDBL_RE.search(text):
        counts["TDbl"] = 1
    return counts


def parse_bonus_counts(sport: str, stats_description: str) -> dict[str, int]:
    """Parse bonus counts from a DK statsDescription string for a supported sport."""
    if sport == "GOLF":
        return _parse_golf_bonus_counts(stats_description)
    if sport == "NBA":
        return _parse_nba_bonus_counts(stats_description)
    return {}
