"""Tests for the ``Optimizer`` orchestrator over a ``LineupSolver``."""

from dk_results.analytics.lineup_solver import Assignment
from dk_results.analytics.optimizer import Optimizer, SelectedPlayer
from dk_results.domain.player import Player
from dk_results.domain.sport import Sport


class _TinySport(Sport):
    name = "TINYTEST"
    positions = ("QB", "RB", "FLEX", "DST")


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


class _RecordingSolver:
    def __init__(self, assignments: list[Assignment] | None) -> None:
        self.assignments = assignments
        self.calls: list[tuple[dict[str, Player], tuple[str, ...], int]] = []

    def solve(self, players, positions, salary_cap):
        self.calls.append((players, positions, salary_cap))
        return self.assignments


def test_get_optimal_lineup_maps_assignments_to_selected_players() -> None:
    players = _slate()
    # A full roster: one assignment per slot in _TinySport.positions.
    solver = _RecordingSolver(
        [
            Assignment("QB1", "QB"),
            Assignment("RB1", "RB"),
            Assignment("RB2", "FLEX"),
            Assignment("49ers ", "DST"),
        ]
    )

    result = Optimizer(_TinySport, players, solver=solver).get_optimal_lineup()

    assert result == [
        SelectedPlayer(players["QB1"], "QB"),
        SelectedPlayer(players["RB1"], "RB"),
        SelectedPlayer(players["RB2"], "FLEX"),
        SelectedPlayer(players["49ers "], "DST"),
    ]


def test_salary_cap_read_from_sport() -> None:
    class _CappedSport(_TinySport):
        salary_cap = 12345

    solver = _RecordingSolver([])
    Optimizer(_CappedSport, _slate(), solver=solver).get_optimal_lineup()

    _, positions, salary_cap = solver.calls[0]
    assert salary_cap == 12345
    assert positions == ("QB", "RB", "FLEX", "DST")


def test_get_optimal_lineup_does_not_mutate_players_dict() -> None:
    players = _slate()
    before = dict(players)

    Optimizer(_TinySport, players).get_optimal_lineup()

    # No rename hack: the digit-leading key survives and nothing is added/removed.
    assert players == before
    assert "49ers " in players
    assert "FortyNiners " not in players


def test_get_optimal_lineup_does_not_mutate_player_pos() -> None:
    players = _slate()
    positions_before = {key: player.pos for key, player in players.items()}

    Optimizer(_TinySport, players).get_optimal_lineup()

    assert {key: player.pos for key, player in players.items()} == positions_before


def test_get_optimal_lineup_end_to_end_is_valid_and_optimal() -> None:
    players = _slate()

    result = Optimizer(_TinySport, players).get_optimal_lineup()

    assert result is not None
    assert sorted(sp.slot for sp in result) == sorted(_TinySport.positions)
    # CBC agrees with GLPK on the objective; assert value, not a tie-broken roster.
    assert sum(sp.player.fpts for sp in result) == 50.0
