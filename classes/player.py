import logging
import logging.config

# load the logging configuration
logging.config.fileConfig("logging.ini")


class Player(object):
    """Create a Player object to represent an athlete for a given sport."""

    def __init__(self, name, pos, salary, game_info, team_abbv, logger=None):
        self.logger = logger or logging.getLogger(__name__)

        self.name = name
        self.pos = pos
        self.salary = int(salary)
        self.game_info = game_info
        self.team_abbv = team_abbv

        # to be updated - update_stats
        self.standings_pos = ""
        self.ownership = 0.0
        self.fpts = 0.0
        self.value = 0.0

        # to be updated - get_matchup_info
        self.matchup_info = ""

    def update_stats(self, pos, perc, fpts):
        """Update class variables from contest standings file (contest-standings-nnnnnnnn.csv)."""
        self.standings_pos = pos
        self.ownership = float(perc.replace("%", "")) / 100
        self.fpts = float(fpts)

        # calculate value
        if self.fpts > 0:
            self.value = self.fpts / (self.salary / 1000)
        else:
            self.value = 0

        self.matchup_info = self.get_matchup_info()

    def get_matchup_info(self):
        """Format matchup_info if there's a home and away team."""
        # wth is this?
        # logger.debug(game_info)
        # this should take care of golf
        if "@" not in self.game_info:
            return self.game_info

        if self.game_info in [
            "In Progress",
            "Final",
            "Postponed",
            "UNKNOWN",
            "Suspended",
            "Delayed",
        ]:
            return self.game_info

        # split game info into matchup_info
        home_team, a = self.game_info.split("@")
        away_team, match_time = a.split(" ", 1)
        # self.logger.debug("home_team: {} away_team: {} t: {}".format(
        #     home_team, away_team, match_time))
        # home_team, away_team = self.game_info.split(" ", 1)[0].split("@")
        if self.team_abbv == home_team:
            matchup_info = "vs. {}".format(away_team)
        else:
            matchup_info = "at {}".format(home_team)
        return matchup_info

    def __str__(self):
        return "[Player] {} {} Sal: ${} - {:.4f} - {} pts Game_Info: {} Team_Abbv: {}".format(
            self.pos,
            self.name,
            self.salary,
            self.ownership,
            self.fpts,
            self.game_info,
            self.team_abbv,
        )

    def __repr__(self):
        return "Player({}, {}, {}, {}, {})".format(
            self.name, self.pos, self.salary, self.game_info, self.team_abbv
        )

    def writeable(self, sport):
        if "PGA" in sport:
            return [self.pos, self.name, self.salary, self.ownership, self.fpts]

        return [
            self.pos,
            self.name,
            self.team_abbv,
            self.matchup_info,
            self.salary,
            self.ownership,
            self.fpts,
            self.value,
        ]
