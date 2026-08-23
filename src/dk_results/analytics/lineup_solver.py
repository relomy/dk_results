"""Solver port for lineup optimization and its PuLP/CBC adapter.

The ``LineupSolver`` port keeps the LP backend swappable: callers depend on the
protocol, not on PuLP. ``PulpCbcSolver`` is the executable-free default, using
PuLP's bundled CBC (no external ``glpsol``). No PuLP type crosses the boundary —
the port speaks only ``Assignment``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

import pulp as pl

from dk_results.domain.player import Player

# LP variable names must be alphanumeric/underscore and may not lead with a
# digit; anything else is replaced generically so any key (e.g. a digit-leading
# DST name like "49ers ") solves without a per-team hack.
_INVALID_LP_NAME_CHARS = re.compile(r"[^A-Za-z0-9_]")


@dataclass(frozen=True)
class Assignment:
    """A player key bound to the roster slot the solver assigned it."""

    player_key: str
    slot: str


class LineupSolver(Protocol):
    """Port: solve a slate into slot assignments, or ``None`` if infeasible."""

    def solve(
        self,
        players: dict[str, Player],
        positions: tuple[str, ...],
        salary_cap: int,
    ) -> list[Assignment] | None: ...


def _sanitize_variable_name(player_key: str, slot: str, index: int) -> str:
    """Return a valid, unique LP variable name derived from a key and slot."""
    cleaned = _INVALID_LP_NAME_CHARS.sub("_", f"{player_key}_{slot}")
    if not cleaned or cleaned[0].isdigit():
        cleaned = f"x_{cleaned}"
    # The index keeps names unique after sanitization collapses distinct keys.
    return f"{cleaned}_{index}"


class PulpCbcSolver:
    """``LineupSolver`` backed by PuLP's bundled CBC (no external executable)."""

    def solve(
        self,
        players: dict[str, Player],
        positions: tuple[str, ...],
        salary_cap: int,
    ) -> list[Assignment] | None:
        prob = pl.LpProblem("DraftKings_Lineup_Optimization", pl.LpMaximize)
        variables = self._create_decision_variables(players)
        self._define_objective(prob, players, variables)
        self._define_budget_constraint(prob, players, variables, salary_cap)
        self._define_player_count_constraint(prob, players, variables)
        self._define_position_constraints(prob, variables, positions)

        pl.PULP_CBC_CMD(msg=0).solve(prob)

        return self._extract_assignments(prob, variables)

    # Helper methods
    def _create_decision_variables(self, players: dict[str, Player]) -> dict[tuple[str, str], pl.LpVariable]:
        variables: dict[tuple[str, str], pl.LpVariable] = {}
        for player_key, player in players.items():
            for pos in player.roster_pos:
                name = _sanitize_variable_name(player_key, pos, len(variables))
                variables[(player_key, pos)] = pl.LpVariable(name, 0, 1, pl.LpInteger)
        return variables

    def _define_objective(
        self,
        prob: pl.LpProblem,
        players: dict[str, Player],
        variables: dict[tuple[str, str], pl.LpVariable],
    ) -> None:
        prob += (
            pl.lpSum(
                players[player_key].fpts * variables[(player_key, pos)]
                for player_key in players
                for pos in players[player_key].roster_pos
            ),
            "Total Points",
        )

    def _define_budget_constraint(
        self,
        prob: pl.LpProblem,
        players: dict[str, Player],
        variables: dict[tuple[str, str], pl.LpVariable],
        salary_cap: int,
    ) -> None:
        total_salary = pl.lpSum(
            players[player_key].salary * variables[(player_key, pos)]
            for player_key in players
            for pos in players[player_key].roster_pos
        )
        prob += (total_salary <= salary_cap, "Budget Constraint")

    def _define_player_count_constraint(
        self,
        prob: pl.LpProblem,
        players: dict[str, Player],
        variables: dict[tuple[str, str], pl.LpVariable],
    ) -> None:
        for player_key in players:
            prob += (
                pl.lpSum(variables[(player_key, pos)] for pos in players[player_key].roster_pos) <= 1,
                f"Only one position for player {player_key}",
            )

    def _define_position_constraints(
        self,
        prob: pl.LpProblem,
        variables: dict[tuple[str, str], pl.LpVariable],
        positions: tuple[str, ...],
    ) -> None:
        for position in dict.fromkeys(positions):
            count = pl.lpSum(var for (_, slot), var in variables.items() if slot == position)
            prob += (count == positions.count(position), f"Position count {position}")

    def _extract_assignments(
        self,
        prob: pl.LpProblem,
        variables: dict[tuple[str, str], pl.LpVariable],
    ) -> list[Assignment] | None:
        if prob.status != 1:
            return None
        # CBC returns binary values as floats (e.g. 0.9999999998), so test with a
        # tolerance rather than exact equality; None (unset) counts as not chosen.
        return [
            Assignment(player_key=player_key, slot=slot)
            for (player_key, slot), var in variables.items()
            if (var.value() or 0) > 0.5
        ]
