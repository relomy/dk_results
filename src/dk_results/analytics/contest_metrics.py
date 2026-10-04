"""Pure contest metrics used by snapshot exports."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from dk_results.analytics.game_status import classify_slot_game_status, is_locked_slot


def _is_finished(slot: Any) -> bool:
    return classify_slot_game_status(slot).remaining is False


def remaining_ownership(slots: Iterable[Any]) -> float:
    """Return ownership percentage points for slots that have not finished."""

    total = 0.0
    for slot in slots:
        if _is_finished(slot):
            continue
        ownership = slot.get("ownership") if isinstance(slot, Mapping) else getattr(slot, "ownership", None)
        if ownership not in (None, ""):
            total += float(ownership) * 100
    return total


def average_remaining_salary(users: Iterable[Any]) -> float | None:
    """Return the slot-weighted salary mean for unfinished known players.

    Hidden players' salaries are unavailable, so locked slots are excluded.
    """

    salaries: list[float] = []
    for user in users:
        lineup = getattr(getattr(user, "lineupobj", None), "lineup", ())
        for player in lineup:
            salary = _known_remaining_salary(player)
            if salary is not None:
                salaries.append(salary)
    return sum(salaries) / len(salaries) if salaries else None


def _known_remaining_salary(slot: Any) -> float | None:
    if is_locked_slot(slot) or _is_finished(slot):
        return None
    salary = getattr(slot, "salary", None)
    return float(salary) if salary is not None else None
