"""Game status classification shared by every snapshot "remaining" metric.

A player's Game status is the raw DraftKings game-info text: a Matchup before
the game, a status word once it starts. This module is the single place that
decides which of those texts mean a player is still to score or is live now.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any, NamedTuple


class GameStatus(NamedTuple):
    """Classification of one Game status text.

    ``remaining`` is True when the player may still score, False when finished.
    ``in_play`` is True when the game is underway (paused games included).
    Both are ``None`` when the text is not a recognized Game status.
    """

    remaining: bool | None
    in_play: bool | None


UNKNOWN = GameStatus(remaining=None, in_play=None)
_IN_PLAY = GameStatus(remaining=True, in_play=True)
_PRE_GAME = GameStatus(remaining=True, in_play=False)
_FINISHED = GameStatus(remaining=False, in_play=False)

_STATUS_BY_TEXT: dict[str, GameStatus] = {
    "in progress": _IN_PLAY,
    "delayed": _IN_PLAY,
    "suspended": _IN_PLAY,
    "final": _FINISHED,
    "postponed": _FINISHED,
    "cancelled": _FINISHED,
    "canceled": _FINISHED,
}


def _normalize(text: Any) -> str:
    return re.sub(r"[\s_-]+", " ", str(text or "")).strip().lower()


def classify_game_status(text: Any) -> GameStatus:
    """Classify raw Game status text; unrecognized text is ``UNKNOWN``."""

    normalized = _normalize(text)
    known = _STATUS_BY_TEXT.get(normalized)
    if known is not None:
        return known
    if "@" in normalized:
        return _PRE_GAME
    return UNKNOWN


def sport_has_game_status(statuses: Iterable[Any]) -> bool:
    """Return True when any status in a sport's player pool classifies as known.

    A sport has no Game status when every player is unknown (today: golf, whose
    players carry only the tournament name). Detected from the data, not from a
    list of sport names.
    """

    return any(classify_game_status(text) is not UNKNOWN for text in statuses)
