"""Create a User object to represent a DraftKings user."""

import logging
import logging.config
from dataclasses import dataclass, field

from .lineup import Lineup

# load the logging configuration
logging.config.fileConfig("logging.ini")


@dataclass
class User:
    """Create a User object to represent a DraftKings user."""

    rank: int | None
    player_id: str
    name: str
    pmr: str
    pts: float | None
    lineup_str: str
    lineup: list = field(default_factory=list)
    lineupobj: Lineup | None = None
    salary: int = 50000

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
