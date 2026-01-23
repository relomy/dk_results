"""Create a Player object to represent an athlete for a given sport."""

import logging
import logging.config
from dataclasses import InitVar, dataclass, field

# load the logging configuration
logging.config.fileConfig("logging.ini")


@dataclass
class Player:
    """Create a Player object to represent an athlete for a given sport."""

    name: str
    pos: str
    roster_pos_raw: str | None
    salary_raw: InitVar[int | str]
    roster_pos: list[str] = field(init=False)
    salary: int = field(init=False)
    game_info: str
    team_abbv: str
    logger: logging.Logger | None = field(default=None, repr=False, compare=False)
    standings_pos: str = ""
    ownership: float = 0.0
    fpts: float = 0.0
    value: float = 0.0
    matchup_info: str = ""

    def __post_init__(self, salary_raw: int | str) -> None:
        self.logger = self.logger or logging.getLogger(__name__)
        self.roster_pos = (
            self.roster_pos_raw.split("/") if self.roster_pos_raw else []
        )
        self.salary = int(salary_raw)

    def update_stats(self, pos: str, perc: str, fpts: str) -> None:
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

    def get_matchup_info(self) -> str:
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
        home_team, at = self.game_info.split("@")
        away_team, _ = at.split(" ", 1)
        # self.logger.debug("home_team: {} away_team: {} t: {}".format(
        #     home_team, away_team, match_time))
        # home_team, away_team = self.game_info.split(" ", 1)[0].split("@")
        if self.team_abbv == home_team:
            matchup_info = "vs. {}".format(away_team)
        else:
            matchup_info = "at {}".format(home_team)
        return matchup_info

    def __str__(self) -> str:
        return "[Player] {} {} Sal: ${} - {:.4f} - {} pts Game_Info: {} Team_Abbv: {}".format(
            self.pos,
            self.name,
            self.salary,
            self.ownership,
            self.fpts,
            self.game_info,
            self.team_abbv,
        )

    def __repr__(self) -> str:
        return "Player({}, {}, {}, {}, {})".format(
            self.name, self.pos, self.salary, self.game_info, self.team_abbv
        )

    def writeable(self, sport: str) -> list:
        if sport in ["PGA", "GOLF"] or "PGA" in sport:
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
