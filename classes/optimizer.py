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
        # Create binary decision variables for player selection (0 or 1)
        selected_players = {
            player: pl.LpVariable(player, 0, 1, pl.LpInteger) for player in self.players
        }

        # Objective function: maximize total points
        self.prob += (
            sum(
                self.players[player].fpts * selected_players[player]
                for player in self.players
            ),
            "Total Points",
        )

        # Define constraint: Total salary should not exceed a certain budget
        budget = 50000
        self.prob += (
            sum(
                self.players[player].salary * selected_players[player]
                for player in self.players
            )
            <= budget,
            "Budget Constraint",
        )

        # Define constraint: Number of selected players should meet lineup requirements
        # Maximum number of players in the lineup
        max_players = self.sport_obj.positions_count

        self.prob += (
            sum(selected_players[player] for player in self.players) == max_players,
            "Required Players",
        )

        # Add position constraints to the problem
        for pos, min_count, max_count in self.sport_obj.position_constraints:
            self.logger.debug(
                f"adding create_position_constraint(selelcted_players, players, {pos}, {min_count}, {max_count})"
            )
            x = self.create_position_constraint(
                selected_players, self.players, pos, min_count, max_count
            )
            self.prob += x

        # Solve the linear programming problem
        # pl.listSolvers(onlyAvailable=True)
        pl.GLPK(msg=0).solve(self.prob)
        # pl.GLPK().solve(self.prob)
        # self.prob.solve()

        optimal_players = []
        # Check the status of the optimization
        if self.prob.status == 1:
            total_points = 0
            total_salary = 0
            self.logger.info("Optimal Lineup:")
            for player, var in selected_players.items():
                if var.value() == 1:
                    self.logger.info(
                        f"{self.players[player].pos} {player}: {self.players[player].salary} salary, {self.players[player].fpts} points"
                    )
                    optimal_players.append(self.players[player])
                    total_points += self.players[player].fpts
                    total_salary += self.players[player].salary

            self.logger.info(
                f"total points {total_points:0.2f} total salary {total_salary}"
            )

            return optimal_players

        self.logger.info("No optimal lineup found within the constraints.")
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
