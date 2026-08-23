"""Solve for a sport's optimal lineup via an injectable ``LineupSolver``.

``Optimizer`` is an orchestrator: it hands the slate to a solver and pairs each
returned assignment with its ``Player``. It never mutates the caller's ``players``
dict nor the shared ``Player.pos`` — the assigned slot rides beside the player in
a frozen ``SelectedPlayer``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Type

from dk_results.analytics.lineup_solver import LineupSolver, PulpCbcSolver
from dk_results.domain.player import Player
from dk_results.domain.sport import Sport


@dataclass(frozen=True)
class SelectedPlayer:
    """A chosen player paired with the roster slot it fills, without mutation."""

    player: Player
    slot: str


class Optimizer:
    """Take a sport and dict of players and solve for the optimal lineup."""

    def __init__(
        self,
        sport_obj: Sport | Type[Sport],
        players: dict[str, Player],
        logger: logging.Logger | None = None,
        solver: LineupSolver | None = None,
    ) -> None:
        self.logger = logger or logging.getLogger(__name__)
        self.sport_obj = sport_obj
        self.players = players
        self.solver: LineupSolver = solver or PulpCbcSolver()

    def get_optimal_lineup(self) -> list[SelectedPlayer] | None:
        assignments = self.solver.solve(
            self.players,
            tuple(self.sport_obj.positions),
            self.sport_obj.salary_cap,
        )
        if assignments is None:
            return None
        return [SelectedPlayer(self.players[a.player_key], a.slot) for a in assignments]
