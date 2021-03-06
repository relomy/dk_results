import csv
from datetime import datetime
import io
import logging
import logging.config
import unicodedata

from .player import Player
from .user import User

# load the logging configuration
logging.config.fileConfig("logging.ini")


class Results(object):
    """Create a Results object which contains the results for a given DraftKings contest."""

    def __init__(self, sport, contest_id, salary_csv_fn, logger=None):
        self.logger = logger or logging.getLogger(__name__)

        self.sport = sport
        self.contest_id = contest_id
        self.players = {}  # dict for players found in salary and standings CSV
        self.users = []  # list of Users found in standings CSV

        # if there's no salary file specified, use the sport/day for the filename
        if not salary_csv_fn:
            salary_csv_fn = f"DKSalaries_{self.sport}_{datetime.now():%A}.csv"

        self.parse_salary_csv(salary_csv_fn)

        self.vips = [
            "aplewandowski",
            "FlyntCoal",
            "Cubbiesftw23",
            "Mcoleman1902",
            "cglenn91",
            "Notorious",
            "Bra3105",
            "ChipotleAddict",
        ]
        self.vip_list = []  # list of VIPs found in standings CSV

        # contest_fn = 'contest-standings-73990354.csv'
        contest_fn = "contest-standings-{}.csv".format(self.contest_id)

        # this pulls the DK users and updates the players stats
        self.parse_contest_standings_csv(contest_fn)

        for vip in self.vip_list:
            self.logger.debug(f"VIP: {vip}")
            # vip.lineup = self.parse_lineup_string(vip.lineup_str)
            vip.set_lineup(self.parse_lineup_string(vip.lineup_str))

        # for k, v in self.players_dict.items():
        #     self.logger.debug("{}: {}".format(k, v))

    def parse_lineup_string(self, lineup_str):
        """Parse VIP's lineup_str and return list of Players."""
        player_list = []
        # dict of positions for each sport
        positions = {
            "CFL": ["QB", "RB", "WR", "TE", "FLEX", "S-FLEX"],
            "MLB": ["P", "C", "1B", "2B", "3B", "SS", "OF"],
            "NBA": ["PG", "SG", "SF", "PF", "C", "G", "F", "UTIL"],
            "NFL": ["QB", "RB", "WR", "TE", "FLEX", "DST"],
            "NHL": ["C", "W", "D", "G", "UTIL"],
            "PGAMain": ["G"],
            "PGAWeekend": ["WG"],
            "PGAShowdown": ["G"],
            "TEN": ["P"],
        }
        splt = lineup_str.split(" ")

        # list comp for indicies of positions in splt
        indices = [i for i, pos in enumerate(splt) if pos in positions[self.sport]]
        # list comp for ending indices in splt. for splicing, the second argument is exclusive
        end_indices = [indices[i] for i in range(1, len(indices))]
        # append size of splt as last index
        end_indices.append(len(splt))
        # self.logger.debug("indices: {}".format(indices))
        # self.logger.debug("end_indices: {}".format(end_indices))
        for i, index in enumerate(indices):
            s = slice(index + 1, end_indices[i])
            name = splt[s]
            if name != "LOCKED":
                # self.logger.debug(name)
                name = " ".join(name)

                # ensure name doesn't have any weird characters
                name = self.strip_accents_and_periods(name)

                if name in self.players:
                    player_list.append(self.players[name])

            if "LOCKED" in name:
                name = "LOCKED 🔒"

        return player_list

    def strip_accents_and_periods(self, name):
        """Strip accents from a given string and replace with letters without accents."""
        # TODO might not want to remove periods for the actual sheet
        return "".join(
            c.replace(".", "")
            for c in unicodedata.normalize("NFD", name)
            if unicodedata.category(c) != "Mn"
        )

    def parse_salary_csv(self, fn):
        """Parse CSV containing players and salary information."""
        with open(fn, mode="r") as f:
            cr = csv.reader(f, delimiter=",")
            slate_list = list(cr)

            for row in slate_list[1:]:  # [1:] to skip header
                if len(row) < 2:
                    continue
                # TODO: might use roster_pos in the future
                pos, _, name, _, roster_pos, salary, game_info, team_abbv, appg = row

                # ensure name doesn't have any weird characters
                name = self.strip_accents_and_periods(name)

                self.players[name] = Player(name, pos, salary, game_info, team_abbv)

    def parse_contest_standings_csv(self, fn):
        """Parse CSV containing contest standings and player ownership."""
        standings = self.load_standings(fn)
        # create a copy of player list
        # player_list = self.players
        for row in standings[1:]:
            rank, id, name, pmr, points, lineup = row[:6]

            # create User object and append to users list
            u = User(rank, id, name, pmr, points, lineup)
            self.users.append(u)

            # find lineup for friends
            if name in self.vips:
                # if we found a VIP, add them to the VIP list
                self.logger.info("found VIP {}".format(name))
                self.vip_list.append(u)

            player_stats = row[7:]
            if player_stats:
                # continue if empty (sometimes happens on the player columns in the standings)
                if all("" == s or s.isspace() for s in player_stats):
                    continue

                name, pos, ownership, fpts = player_stats
                name = self.strip_accents_and_periods(name)

                # if 'Jr.' in name:
                #     name = name.replace('Jr.', 'Jr')

                self.players[name].update_stats(pos, ownership, fpts)

    def load_standings(self, fn):
        """Load standings CSV and return list."""
        with open(fn, "rb") as csvfile:
            lines = io.TextIOWrapper(csvfile, encoding="utf-8", newline="\r\n")
            rdr = csv.reader(lines, delimiter=",")
            return list(rdr)

    def players_to_values(self):
        # sort players by ownership
        sorted_players = sorted(self.players, key=lambda x: self.players[x].ownership, reverse=True)
        # for p in self.players.values():
        #     print(p.perc)
        #     print()
        return [
            self.players[p].writeable() for p in sorted_players if self.players[p].ownership > 0
        ]

