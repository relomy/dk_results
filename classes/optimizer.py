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

        # solver_list = pl.listSolvers()
        # self.logger.debug(solver_list)

        # Create the 'prob' variable to contain the problem data
        self.prob = pl.LpProblem("DraftKings_Lineup_Optimization", pl.LpMaximize)

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

    # def create_decision_variables(self):
    #     return {
    #         player: pl.LpVariable(player, 0, 1, pl.LpInteger) for player in self.players
    #     }
    def create_decision_variables(self):
        selected_players = {}
        for player in self.players:
            selected_positions = self.players[player].roster_pos
            for pos in selected_positions:
                selected_players[(player, pos)] = pl.LpVariable(
                    f"{player}_{pos}", 0, 1, pl.LpInteger
                )
        return selected_players

    def define_budget_constraint(self, selected_players):
        budget = 50000
        total_salary = sum(
            self.players[player].salary * selected_players[(player, pos)]
            for player in self.players
            for pos in self.players[player].roster_pos
        )
        self.prob += (total_salary <= budget, "Budget Constraint")

    def define_player_count_constraint(self, selected_players):
        for player in self.players:
            self.prob += (
                sum(
                    selected_players[player, pos]
                    for pos in self.players[player].roster_pos
                )
                <= 1,
                f"Only one position for player {player}",
            )

    def define_objective(self, selected_players):
        self.prob += (
            sum(
                self.players[player].fpts * selected_players[(player, pos)]
                for player in self.players
                for pos in self.players[player].roster_pos
            ),
            "Total Points",
        )

    def define_position_constraints(self, selected_players):
        for position in self.sport_obj.positions:
            x = self.create_position_constraint(selected_players, position)
            self.prob += x

    def create_position_constraint(self, selected_players, position):
        count = sum(
            selected_players[(player, position)]  # use tuple as the key
            for player in self.players
            if position in self.players[player].roster_pos
        )
        return count == self.sport_obj.positions.count(position)

    def solve_problem(self):
        pl.GLPK(msg=1).solve(self.prob)

    def extract_optimal_lineup(self, selected_players):
        optimal_players = []
        if self.prob.status == 1:
            total_points = 0
            total_salary = 0
            for player, var in selected_players.items():
                if var.value() == 1:
                    optimal_player = self.players[player[0]]
                    optimal_player.pos = player[1]
                    optimal_players.append(optimal_player)
                    total_points += self.players[player[0]].fpts
                    total_salary += self.players[player[0]].salary
            return optimal_players
        return None
