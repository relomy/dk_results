"""Create a Results object which contains the results for a given DraftKings contest."""

import copy
import csv
from datetime import datetime
import io
import logging
import logging.config
import unicodedata
import os

from .player import Player
from .user import User

# load the logging configuration
logging.config.fileConfig("logging.ini")


class Results:
    """Create a Results object which contains the results for a given DraftKings contest."""

    def __init__(
        self, sport, contest_id, salary_csv_fn, positions_paid=None, logger=None
    ):
        self.logger = logger or logging.getLogger(__name__)

        self.sport = sport
        self.contest_id = contest_id
        self.players = {}  # dict for players found in salary and standings CSV
        self.users = []  # list of Users found in standings CSV
        self.positions_paid = positions_paid

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
            "CFB": ["QB", "RB", "RB", "WR", "WR", "WR", "FLEX", "S-FLEX"],
            "MLB": ["P", "C", "1B", "2B", "3B", "SS", "OF"],
            "NBA": ["PG", "SG", "SF", "PF", "C", "G", "F", "UTIL"],
            "NFL": ["QB", "RB", "WR", "TE", "FLEX", "DST"],
            "NFLShowdown": ["CPT", "FLEX"],
            "NHL": ["C", "W", "D", "G", "UTIL"],
            "GOLF": ["G"],
            "PGAMain": ["G"],
            "PGAWeekend": ["WG"],
            "PGAShowdown": ["G"],
            "TEN": ["P"],
            "XFL": ["QB", "RB", "WR", "FLEX", "DST"],
            "MMA": ["F"],
            "LOL": ["CPT", "TOP", "JNG", "MID", "ADC", "SUP", "TEAM"],
            "NAS": ["D"],
        }

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
            "papagates",
            "EmpireMaker2",
        ]
        self.vip_list = []  # list of VIPs found in standings CSV

        # contest_fn = 'contest-standings-73990354.csv'
        contest_dir = "contests"
        contest_fn = os.path.join(
            contest_dir, "contest-standings-{}.csv".format(self.contest_id)
        )

        # this pulls the DK users and updates the players stats
        self.parse_contest_standings_csv(contest_fn)

        for vip in self.vip_list:
            self.logger.debug("VIP: %s", vip)
            # vip.lineup = self.parse_lineup_string(vip.lineup_str)
            vip.set_lineup(self.parse_lineup_string(vip.lineup_str))

        # for k, v in self.players_dict.items():
        #     self.logger.debug("{}: {}".format(k, v))

    def parse_lineup_string(self, lineup_str):
        """Parse VIP's lineup_str and return list of Players."""
        player_list = []

        splt = lineup_str.split(" ")

        # list comp for indicies of positions in splt
        indices = [i for i, pos in enumerate(splt) if pos in self.POSITIONS[self.sport]]
        # list comp for ending indices in splt. for splicing, the second argument is exclusive
        end_indices = [indices[i] for i in range(1, len(indices))]
        # append size of splt as last index
        end_indices.append(len(splt))
        # self.logger.debug("indices: {}".format(indices))
        # self.logger.debug("end_indices: {}".format(end_indices))
        for i, index in enumerate(indices):
            name_slice = slice(index + 1, end_indices[i])
            pos_slice = slice(index, index + 1)
            name = splt[name_slice]
            position = splt[pos_slice][0]

            if "LOCKED" in name:
                name = "LOCKED 🔒"
                player_list.append(Player(name, position, 0, None, None))
            else:
                # self.logger.debug(name)
                name = " ".join(name)

                # ensure name doesn't have any weird characters
                name = self.strip_accents_and_periods(name)

                if name in self.players:
                    # check if position is different (FLEX, etc.)
                    if position != self.players[name].pos:
                        # create copy of local Player to update player's position for the sheet
                        player_copy = copy.deepcopy(self.players[name])
                        player_copy.pos = position
                        player_list.append(player_copy)
                    else:
                        player_list.append(self.players[name])

        # sort by DraftKings roster order (RB, RB, WR, WR, etc.), then name
        sorted_list = sorted(
            player_list, key=lambda x: (self.POSITIONS[self.sport].index(x.pos), x.name)
        )

        return sorted_list

    def strip_accents_and_periods(self, name):
        """Strip accents from a given string and replace with letters without accents."""
        return "".join(
            # c.replace(".", "")
            c
            for c in unicodedata.normalize("NFD", name)
            if unicodedata.category(c) != "Mn"
        )

    def parse_salary_csv(self, filename):
        """Parse CSV containing players and salary information."""
        with open(filename, mode="r") as fp:
            cr = csv.reader(fp, delimiter=",")
            slate_list = list(cr)

            for row in slate_list[1:]:  # [1:] to skip header
                if len(row) < 2:
                    continue
                # TODO: might use roster_pos in the future
                # pos, _, name, _, roster_pos, salary, game_info, team_abbv, appg
                pos, _, name, _, _, salary, game_info, team_abbv, _ = row

                # ensure name doesn't have any weird characters
                name = self.strip_accents_and_periods(name)

                self.players[name] = Player(name, pos, salary, game_info, team_abbv)

    def parse_contest_standings_csv(self, filename):
        """Parse CSV containing contest standings and player ownership."""
        standings = self.load_standings(filename)

        # showdown only
        showdown_captains = {}

        # create a copy of player list
        # player_list = self.players
        for row in standings[1:]:
            # catch empty rows
            if not row:
                continue

            rank, player_id, name, pmr, points, lineup = row[:6]

            rank = int(rank)
            points = float(points)

            # create User object and append to users list
            user = User(rank, player_id, name, pmr, points, lineup)
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
                    if self.sport in ["NFL", "NFLShowdown", "CFB"]:

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
                name = self.strip_accents_and_periods(name)

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

        if self.sport == "NFLShowdown":
            sorted_captains = {
                k: v
                for k, v in sorted(
                    showdown_captains.items(),
                    key=lambda item: item[1],
                    reverse=True,
                )
            }

            top_ten_cpts = list(sorted_captains)[:10]

            print("Top 10 captains:")
            for cpt in top_ten_cpts:
                self.get_showdown_captain_percent(cpt, showdown_captains)

    def add_player_to_dict(self, player, dictionary):
        if player.name not in dictionary:
            # initialize player count to 1
            dictionary[player.name] = 1

        # add players
        dictionary[player.name] += 1

        return dictionary

    # def add_to_showdown_dict(self, player):
    #     if player.name not in self.showdown_captains:
    #         # initialize player count to 1
    #         self.showdown_captains[player.name] = 1

    #     # add players
    #     self.showdown_captains[player.name] += 1

    def get_showdown_captain_percent(self, player, showdown_captains):
        percent = 0.0
        num_users = len(self.users)
        percent = float(showdown_captains[player] / num_users) * 100
        print(
            "{}: {:0.2f}% [{}/{}]".format(
                player, percent, showdown_captains[player], num_users
            )
        )

    def load_standings(self, filename):
        """Load standings CSV and return list."""
        with open(filename, "rb") as csvfile:
            lines = io.TextIOWrapper(csvfile, encoding="utf-8", newline="\n")
            rdr = csv.reader(lines, delimiter=",")
            return list(rdr)

    def players_to_values(self, sport):
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
