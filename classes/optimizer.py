# import csv
import logging
import logging.config

import pulp as pl

from .sport import Sport

logging.config.fileConfig("logging.ini")


class Optimizer:
    """Take a sport and list of players and solve for optimal lineup."""

    def __init__(self, sport_obj: Sport, players, logger=None):
        self.logger = logger or logging.getLogger(__name__)

        self.sport_obj = sport_obj

        solver_list = pl.listSolvers()
        self.logger.debug(solver_list)

        # Create the 'prob' variable to contain the problem data
        self.prob = pl.LpProblem("DraftKings Lineup Optimization", pl.LpMaximize)

        self.players = players

        if "49ers " in players:
            players["FortyNiners "] = players["49ers "]
            del players["49ers "]

    def get_optimal_lineup(self) -> dict():
        selected_players = self.create_decision_variables()
        self.define_objective(selected_players)
        self.define_budget_constraint(selected_players)
        self.define_player_count_constraint(selected_players)
        self.define_position_constraints(selected_players)

        self.solve_problem()

        return self.extract_optimal_lineup(selected_players)

    # Helper methods

    def create_decision_variables(self):
        return {
            player: pl.LpVariable(player, 0, 1, pl.LpInteger) for player in self.players
        }

    def define_objective(self, selected_players):
        self.prob += (
            sum(
                self.players[player].fpts * selected_players[player]
                for player in self.players
            ),
            "Total Points",
        )

    def define_budget_constraint(self, selected_players):
        budget = 50000
        self.prob += (
            sum(
                self.players[player].salary * selected_players[player]
                for player in self.players
            )
            <= budget,
            "Budget Constraint",
        )

    def define_player_count_constraint(self, selected_players):
        max_players = self.sport_obj.positions_count
        self.prob += (
            sum(selected_players[player] for player in self.players) == max_players,
            "Required Players",
        )

    def define_position_constraints(self, selected_players):
        for pos, min_count, max_count in self.sport_obj.position_constraints:
            x = self.create_position_constraint(
                selected_players, self.players, pos, min_count, max_count
            )
            self.prob += x

    def solve_problem(self):
        pl.GLPK(msg=0).solve(self.prob)

    def extract_optimal_lineup(self, selected_players):
        optimal_players = []
        if self.prob.status == 1:
            total_points = 0
            total_salary = 0
            for player, var in selected_players.items():
                if var.value() == 1:
                    optimal_players.append(self.players[player])
                    total_points += self.players[player].fpts
                    total_salary += self.players[player].salary
            return optimal_players
        return None

    # Define a function to create position constraints
    def create_position_constraint(
        self, selected_players, players, position, min_count, max_count
    ):
        count = sum(
            selected_players[player]
            for player in players
            if players[player].pos == position
        )
        if max_count is None:
            return count == min_count
        else:
            return count >= min_count and count <= max_count
