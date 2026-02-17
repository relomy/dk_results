"""Create a User object to represent a DraftKings user."""

from dataclasses import dataclass, field

from dk_results.logging import configure_logging

from .lineup import Lineup

# load the logging configuration
configure_logging()


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

    def set_lineup(self, lineup: list) -> None:
        """Set lineup for User object."""
        for player in lineup:
            self.salary -= player.salary

        self.lineup = lineup

    def set_lineup_obj(self, lineup: Lineup) -> None:
        """Attach a Lineup object and update remaining salary."""
        self.lineupobj = lineup

        for player in lineup.lineup:
            self.salary -= player.salary

    def __str__(self) -> str:
        return "[User]: Name: {} Rank: {} PMR: {} Pts: {} Salary: {} LU: {}".format(
            self.name, self.rank, self.pmr, self.pts, self.salary, self.lineup_str
        )

    def __repr__(self) -> str:
        return "User({}, {}, {}, {}, {})".format(self.name, self.rank, self.pmr, self.pts, self.lineup_str)
