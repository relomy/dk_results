"""Pure contest metrics shared by live sheets and snapshot exports."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any


def remaining_ownership(slots: Iterable[Any]) -> float:
    """Return ownership percentage points for slots that have not finished."""

    total = 0.0
    for slot in slots:
        game_info = slot.get("game_info") if isinstance(slot, Mapping) else getattr(slot, "game_info", "")
        if str(game_info).strip() == "Final":
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
            if str(getattr(player, "game_info", "")).strip() != "Final" and getattr(player, "salary", None) is not None:
                salaries.append(float(player.salary))
    return sum(salaries) / len(salaries) if salaries else None
