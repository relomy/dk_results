"""Create a Results object which contains the results for a given DraftKings contest."""

import csv
import io
import logging
import os
from datetime import datetime
from typing import Iterable, Type

from .lineup import Lineup, normalize_name, parse_lineup_string
from .player import Player
from .sport import Sport
from .user import User


class Results:
    """Parse salary and standings data for a DraftKings contest."""

    def __init__(
        self,
        sport_obj: Sport | Type[Sport],
        contest_id: int,
        salary_csv_fn: str,
        positions_paid: int | None = None,
        salary_rows: list[list[str]] | None = None,
        standings_rows: list[list[str]] | None = None,
        vips: list[str] | None = None,
        logger: logging.Logger | None = None,
    ):
        self.logger = logger or logging.getLogger(__name__)

        self.sport_obj = sport_obj
        self.contest_id = contest_id
        self.players = {}  # dict for players found in salary and standings CSV
        self.users = []  # list of Users found in standings CSV
        self.positions_paid: int | None = positions_paid
        self.name: str = ""

        self.min_rank = 0
        self.min_cash_pts = 1000.0

        # non cashing values (players outside the cash line)
        self.avg_cashless_pmr = 0
        self.non_cashing_players = {}
        self.non_cashing_users = 0
        self.non_cashing_total_pmr = 0
        self.non_cashing_avg_pmr = 0.0

        # dict of positions for each sport
        self.POSITIONS = {
            "XFL": ["QB", "RB", "WR", "FLEX", "DST"],
        }

        # if there's no salary file specified, use the sport/day for the filename
        if not salary_csv_fn:
            salary_csv_fn = (
                f"DKSalaries_{self.sport_obj.sport_name}_{datetime.now():%A}.csv"
            )

        if salary_rows is not None:
            self.parse_salary_rows(salary_rows)
        else:
            self.parse_salary_csv(salary_csv_fn)

        self.vips = list(vips) if vips else []
        self.vip_list = []  # list of VIPs found in standings CSV

        # contest_fn = 'contest-standings-73990354.csv'
        contest_dir = "contests"
        contest_fn = os.path.join(
            contest_dir, "contest-standings-{}.csv".format(self.contest_id)
        )

        # this pulls the DK users and updates the players stats
        if standings_rows is not None:
            self.parse_contest_standings_rows(standings_rows)
        else:
            self.parse_contest_standings_csv(contest_fn)

        for vip in self.vip_list:
            self.logger.debug("VIP: %s", vip)
            # vip.lineup = self.parse_lineup_string(vip.lineup_str)
            vip.set_lineup(self.parse_lineup_string(vip.lineup_str))

        # for k, v in self.players_dict.items():
        #     self.logger.debug("{}: {}".format(k, v))

    def parse_lineup_string(self, lineup_str: str) -> list[Player]:
        """Parse VIP's lineup_str and return list of Players."""
        return parse_lineup_string(self.sport_obj, self.players, lineup_str)

    def parse_salary_csv(self, filename: str) -> None:
        """Parse CSV containing players and salary information."""
        with open(filename, mode="r") as fp:
            cr = csv.reader(fp, delimiter=",")
            self.parse_salary_rows(cr)

    def parse_salary_rows(self, rows: Iterable[list[str]]) -> None:
        """Parse salary rows, including header row at index 0."""
        rows_iter = iter(rows)
        next(rows_iter, None)
        for row in rows_iter:
            if len(row) < 2:
                continue
            # TODO: might use roster_pos in the future
            # pos, _, name, _, roster_pos, salary, game_info, team_abbv, appg
            pos, _, name, _, roster_pos, salary, game_info, team_abbv, _ = row

            # ensure name doesn't have any weird characters
            name = normalize_name(name)

            self.players[name] = Player(
                name, pos, roster_pos, salary, game_info, team_abbv
            )

    def parse_contest_standings_csv(self, filename: str) -> None:
        """Parse CSV containing contest standings and player ownership."""
        with open(filename, "rb") as csvfile:
            lines = io.TextIOWrapper(csvfile, encoding="utf-8", newline="\n")
            rdr = csv.reader(lines, delimiter=",")
            self.parse_contest_standings_rows(rdr)

    def parse_contest_standings_rows(self, standings: Iterable[list[str]]) -> None:
        """Parse contest standings rows, including header row at index 0."""
        standings_iter = iter(standings)
        next(standings_iter, None)

        # showdown only
        showdown_captains = {}

        # create a copy of player list
        # player_list = self.players
        for row in standings_iter:
            # catch empty rows
            if not row:
                continue

            rank, player_id, name, pmr, points, lineup = row[:6]

            if rank and points:
                rank = int(rank)
                points = float(points)

            # create User object and append to users list
            lineupobj = Lineup(self.sport_obj, self.players, lineup)
            user = User(rank, player_id, name, pmr, points, lineup)
            user.set_lineup_obj(lineupobj)
            self.users.append(user)

            # find lineup for friends
            if name in self.vips:
                # if we found a VIP, add them to the VIP list
                self.logger.info("found VIP %s", name)
                self.vip_list.append(user)

            # keep track of minimum pts to cash
            if self.positions_paid:
                # set minimum cash pts
                if self.positions_paid >= rank and self.min_cash_pts > points:
                    self.min_rank = rank
                    self.min_cash_pts = points
                else:
                    self.non_cashing_total_pmr += float(pmr)

                    # let's only parse lineups for NFL right now
                    if self.sport_obj.name in [
                        "NFL",
                        "NFLShowdown",
                        "CFB",
                        "NBA",
                    ]:
                        # for those below minimum cash, let's find their players
                        lineup_players = self.parse_lineup_string(lineup)

                        for player in lineup_players:
                            if player.pos == "CPT":
                                showdown_captains = self.add_player_to_dict(
                                    player, showdown_captains
                                )

                            # we only care about players that are not done yet
                            if player.game_info == "Final":
                                continue

                            self.non_cashing_players = self.add_player_to_dict(
                                player, self.non_cashing_players
                            )

                        self.non_cashing_users += 1

            player_stats = row[7:]
            if player_stats:
                # continue if empty (sometimes happens on the player columns in the standings)
                if all(s == "" or s.isspace() for s in player_stats):
                    continue

                name, pos, ownership, fpts = player_stats
                name = normalize_name(name)

                # if 'Jr.' in name:
                #     name = name.replace('Jr.', 'Jr')
                try:
                    self.players[name].update_stats(pos, ownership, fpts)
                except KeyError:
                    self.logger.error("Player %s not found in players[] dict", name)

        if self.non_cashing_users > 0 and self.non_cashing_total_pmr > 0:
            self.non_cashing_avg_pmr = (
                self.non_cashing_total_pmr / self.non_cashing_users
            )

        self.logger.debug(
            "non_cashing: users {} total_pmr: {} avg_pmr: {}".format(
                self.non_cashing_users,
                self.non_cashing_total_pmr,
                self.non_cashing_avg_pmr,
            )
        )

        if self.sport_obj.sport_name == "NFLShowdown":
            sorted_captains = {
                k: v
                for k, v in sorted(
                    showdown_captains.items(),
                    key=lambda item: item[1],
                    reverse=True,
                )
            }

            top_ten_cpts = list(sorted_captains)[:10]

            self.logger.info("Top 10 captains:")
            for cpt in top_ten_cpts:
                self.get_showdown_captain_percent(cpt, showdown_captains)

    def add_player_to_dict(
        self, player: Player, dictionary: dict[str, int]
    ) -> dict[str, int]:
        if player.name not in dictionary:
            dictionary[player.name] = 0

        # add players
        dictionary[player.name] += 1

        return dictionary

    def get_showdown_captain_percent(
        self, player: str, showdown_captains: dict[str, int]
    ) -> None:
        percent = 0.0
        num_users = len(self.users)
        percent = float(showdown_captains[player] / num_users) * 100
        print(
            "{}: {:0.2f}% [{}/{}]".format(
                player, percent, showdown_captains[player], num_users
            )
        )

    def load_standings(self, filename: str) -> list[list[str]]:
        """Load standings CSV and return list."""
        with open(filename, "rb") as csvfile:
            lines = io.TextIOWrapper(csvfile, encoding="utf-8", newline="\n")
            rdr = csv.reader(lines, delimiter=",")
            return list(rdr)

    def players_to_values(self, sport: str) -> list[list]:
        """Return list for DFSSheet values."""
        # sort players by ownership
        sorted_players = sorted(
            self.players, key=lambda x: self.players[x].ownership, reverse=True
        )
        # for p in self.players.values():
        #     print(p.perc)
        #     print()
        return [
            self.players[p].writeable(sport)
            for p in sorted_players
            if self.players[p].ownership > 0
        ]

    def get_players(self) -> dict[str, Player]:
        return self.players
