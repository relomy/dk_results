"""Parsing rules for DraftKings bonus opportunities from statsDescription."""

from __future__ import annotations

import re

_GOLF_TOKEN_RE = re.compile(r"(?<!\w)(\d+)\s*(EAG|BOFR|BIR3\+)(?!\w)")
_NBA_DDBL_RE = re.compile(r"\bDDbl\b")
_NBA_TDBL_RE = re.compile(r"\bTDbl\b")
_MLB_HR_RE = re.compile(r"(?<!\w)(\d+)\s*HR(?!\w)")
_SOC_GOAL_RE = re.compile(r"(?<!\w)(\d+)\s*G(?!\w)")

# NOTE: unverified against a real DK statsDescription sample; DK's exact token
# spelling for these football yardage bonuses is a best guess (see NFL/CFB
# bonus announcement work) and should be corrected once a live example is seen.
_NFL_100_REC_RE = re.compile(r"\b100YdRec\b")
_NFL_100_RUSH_RE = re.compile(r"\b100YdRush\b")
_NFL_300_PASS_RE = re.compile(r"\b300YdPass\b")


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


def _parse_mlb_bonus_counts(stats_description: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    m = _MLB_HR_RE.search(stats_description or "")
    if m and (n := int(m.group(1))) > 0:
        counts["HR"] = n
    return counts


def _parse_soc_bonus_counts(stats_description: str) -> dict[str, int]:
    m = _SOC_GOAL_RE.search(stats_description or "")
    if m and (n := int(m.group(1))) > 0:
        return {"G": n}
    return {}


def _parse_football_bonus_counts(stats_description: str) -> dict[str, int]:
    text = stats_description or ""
    counts: dict[str, int] = {}
    if _NFL_100_REC_RE.search(text):
        counts["100YdRec"] = 1
    if _NFL_100_RUSH_RE.search(text):
        counts["100YdRush"] = 1
    if _NFL_300_PASS_RE.search(text):
        counts["300YdPass"] = 1
    return counts


def parse_bonus_counts(sport: str, stats_description: str) -> dict[str, int]:
    """Parse bonus counts from a DK statsDescription string for a supported sport."""
    if sport == "GOLF":
        return _parse_golf_bonus_counts(stats_description)
    if sport == "NBA":
        return _parse_nba_bonus_counts(stats_description)
    if sport == "MLB":
        return _parse_mlb_bonus_counts(stats_description)
    if sport == "SOC":
        return _parse_soc_bonus_counts(stats_description)
    if sport in ("NFL", "CFB"):
        return _parse_football_bonus_counts(stats_description)
    return {}
