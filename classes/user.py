import logging
import logging.config

# load the logging configuration
logging.config.fileConfig('logging.ini')


class User(object):
    def __init__(self, rank, id, name, pmr, pts, lineup_str):
        self.rank = rank
        self.id = id
        self.name = name
        self.pmr = pmr
        self.pts = pts
        self.lineup_str = lineup_str

        # self.lineup = lineup_str.split()

    def __repr__(self):
        return "User({}, {}, {}, {}, {})".format(self.name, self.rank, self.pmr, self.pts, self.lineup_str)
