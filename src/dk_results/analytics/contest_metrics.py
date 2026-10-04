"""Pure contest metrics shared by live sheets and snapshot exports."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from dk_results.analytics.game_status import classify_game_status


def _is_finished(game_info: Any) -> bool:
    return classify_game_status(game_info).remaining is False


def remaining_ownership(slots: Iterable[Any]) -> float:
    """Return ownership percentage points for slots that have not finished."""

    total = 0.0
    for slot in slots:
        game_info = slot.get("game_info") if isinstance(slot, Mapping) else getattr(slot, "game_info", "")
        if _is_finished(game_info):
            continue
        ownership = slot.get("ownership") if isinstance(slot, Mapping) else getattr(slot, "ownership", None)
        if ownership not in (None, ""):
            total += float(ownership) * 100
    return total


def average_remaining_salary(users: Iterable[Any]) -> float | None:
    """Return the slot-weighted average salary for unfinished lineup slots."""

    salaries: list[float] = []
    for user in users:
        lineup = getattr(getattr(user, "lineupobj", None), "lineup", ())
        for player in lineup:
            if not _is_finished(getattr(player, "game_info", "")) and getattr(player, "salary", None) is not None:
                salaries.append(float(player.salary))
    return sum(salaries) / len(salaries) if salaries else None
