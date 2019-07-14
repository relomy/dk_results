import logging
import logging.config

# load the logging configuration
logging.config.fileConfig('logging.ini')


class User(object):
    """Create a User object to represent a DraftKings user."""

    def __init__(self, rank, id, name, pmr, pts, lineup_str):
        self.rank = rank
        self.id = id
        self.name = name
        self.pmr = pmr
        self.pts = pts
        self.lineup_str = lineup_str

        self.lineup = []
        self.salary = 50000

        # self.lineup = lineup_str.split()

    def set_lineup(self, lineup):
        for p in lineup:
            self.salary -= p.salary
        self.lineup = lineup

    def __str__(self):
        return "[User]: Name: {} Rank: {} PMR: {} Pts: {} Salary: {} LU: {}".format(self.name, self.rank, self.pmr, self.pts, self.salary, self.lineup_str)

    def __repr__(self):
        return "User({}, {}, {}, {}, {})".format(self.name, self.rank, self.pmr, self.pts, self.lineup_str)
