"""Create a User object to represent a DraftKings user."""

import logging
import logging.config

from .lineup import Lineup

# load the logging configuration
logging.config.fileConfig("logging.ini")


class User:
    """Create a User object to represent a DraftKings user."""

    def __init__(self, rank, player_id, name, pmr, pts, lineup_str):
        self.rank = rank
        self.player_id = player_id
        self.name = name
        self.pmr = pmr
        self.pts = pts
        self.lineup_str = lineup_str

        self.lineup = []
        self.lineupobj = None
        self.salary = 50000

        # self.lineup = lineup_str.split()

    def set_lineup(self, lineup):
        """Set lineup for User object."""
        for player in lineup:
            self.salary -= player.salary

        self.lineup = lineup

    def set_lineup_obj(self, lineup: Lineup):
        self.lineupobj = lineup

        for player in lineup.lineup:
            self.salary -= player.salary

    def __str__(self):
        return "[User]: Name: {} Rank: {} PMR: {} Pts: {} Salary: {} LU: {}".format(
            self.name, self.rank, self.pmr, self.pts, self.salary, self.lineup_str
        )

    def __repr__(self):
        return "User({}, {}, {}, {}, {})".format(
            self.name, self.rank, self.pmr, self.pts, self.lineup_str
        )
