"""Tests for the ``PulpCbcSolver`` adapter behind the ``LineupSolver`` port."""

from dk_results.analytics.lineup_solver import Assignment, PulpCbcSolver
from dk_results.domain.player import Player


def _player(name: str, roster_pos: str, salary: int, fpts: float) -> Player:
    player = Player(
        name=name,
        pos="",
        roster_pos_raw=roster_pos,
        salary_raw=salary,
        game_info="Final",
        team_abbv="TM",
    )
    player.fpts = fpts
    return player


def _slate() -> dict[str, Player]:
    return {
        "QB1": _player("QB One", "QB", 5000, 20.0),
        "RB1": _player("RB One", "RB/FLEX", 5000, 15.0),
        "RB2": _player("RB Two", "RB/FLEX", 4000, 10.0),
        "49ers ": _player("49ers ", "DST", 3000, 5.0),
    }


def test_create_decision_variables_one_per_roster_position() -> None:
    players = _slate()

    variables = PulpCbcSolver()._create_decision_variables(players)

    # One decision variable per (player, roster position) pair.
    assert set(variables) == {
        ("QB1", "QB"),
        ("RB1", "RB"),
        ("RB1", "FLEX"),
        ("RB2", "RB"),
        ("RB2", "FLEX"),
        ("49ers ", "DST"),
    }


def test_create_decision_variables_sanitizes_digit_leading_key() -> None:
    players = {"49ers ": _player("49ers ", "DST", 3000, 5.0)}

    variables = PulpCbcSolver()._create_decision_variables(players)

    name = variables[("49ers ", "DST")].name
    assert not name[0].isdigit()  # LP names may not lead with a digit
    assert " " not in name  # nor contain spaces


def test_solve_returns_optimal_assignments_for_feasible_slate() -> None:
    players = _slate()
    positions = ("QB", "RB", "FLEX", "DST")

    assignments = PulpCbcSolver().solve(players, positions, salary_cap=50000)

    assert assignments is not None
    assert all(isinstance(a, Assignment) for a in assignments)
    assert sorted(a.slot for a in assignments) == sorted(positions)
    # Objective: every player fits under the cap, so all are selected.
    assert {a.player_key for a in assignments} == set(players)


def test_solve_returns_none_when_infeasible() -> None:
    players = _slate()
    positions = ("QB", "RB", "FLEX", "DST")

    # Cap far below the cheapest valid lineup makes the problem infeasible.
    assignments = PulpCbcSolver().solve(players, positions, salary_cap=1)

    assert assignments is None
