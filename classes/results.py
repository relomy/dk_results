import csv
import datetime
import io
import logging
import logging.config
import unicodedata

from .player import Player
from .user import User


# load the logging configuration
logging.config.fileConfig('logging.ini')
# logger = logging.getLogger(__name__)


def strip_accents(s):
    """Strip accents from a given string and replace with letters without accents."""
    return ''.join(c for c in unicodedata.normalize('NFD', s)
                   if unicodedata.category(c) != 'Mn')


class Results(object):
    """Create a Results object which contains the results for a given DraftKings contest."""

    def __init__(self, sport, contest_id, salary_csv_fn, logger=None):
        self.logger = logger or logging.getLogger(__name__)

        self.sport = sport
        self.contest_id = contest_id
        self.players = []
        self.complete_players = []
        self.users = []

        # if there's no salary file specified, use the sport/day for the filename
        if not salary_csv_fn:
            salary_csv_fn = "DKSalaries_{}_{}.csv".format(
                self.sport, datetime.datetime.now().strftime('%A'))

        self.read_salary_csv(salary_csv_fn)
        self.logger.debug(self.players)

        self.vips = ['aplewandowski', 'FlyntCoal', 'Cubbiesftw23', 'Mcoleman1902',
                     'cglenn91', 'Notorious', 'Bra3105', 'ChipotleAddict']
        self.vip_list = []

        contest_fn = 'contest-standings-73165360.csv'

        # this pulls the DK users and updates the players stats
        self.parse_contest_standings(contest_fn)

        for player in self.complete_players:
            self.logger.debug(player)

        for vip in self.vip_list:
            self.logger.debug("VIP: {}".format(vip))

        for p in self.complete_players[:5]:
            self.logger.info(p)

    def read_salary_csv(self, fn):
        with open(fn, mode='r') as f:
            cr = csv.reader(f, delimiter=',')
            slate_list = list(cr)

            for row in slate_list[1:]:  # [1:] to skip header
                if len(row) < 2:
                    continue
                # TODO: might use roster_pos in the future
                pos, _, name, _, roster_pos, salary, game_info, team_abbv, appg = row
                self.players.append(Player(name, pos, salary, game_info, team_abbv))

    def parse_contest_standings(self, fn):
        list = self.load_standings(fn)
        # create a copy of player list
        player_list = self.players
        for row in list[1:]:
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
                if all('' == s or s.isspace() for s in player_stats):
                    continue

                name, pos, perc, fpts = player_stats
                name = strip_accents(name)

                for i, player in enumerate(player_list):
                    if name == player.name:
                        self.logger.debug(
                            "name {} MATCHES player.name {}!".format(name, player.name))
                        player.update_stats(pos, perc, fpts)
                        # update player list
                        self.complete_players.append(player)
                        del(player_list[i])
                        break
                    # else:
                    #     self.logger.debug(
                    #         "name {} DOES NOT MATCH player.name {}!".format(name, player.name))

                # for i, player in enumerate(self.players):
                #     if name == player.name:
                #         self.logger.debug(
                #             "name {} MATCHES player.name {}!".format(name, player.name))
                #         player.update_stats(pos, perc, fpts)
                #         # update player list
                #         self.players[i] = player
                #         self.logger.info(self.players[i])
                #         break
                #     else:
                #         self.logger.debug(
                #             "name {} DOES NOT MATCH player.name {}!".format(name, player.name))

    def load_standings(self, fn):
        with open(fn, 'rb') as csvfile:
            lines = io.TextIOWrapper(csvfile, encoding='utf-8', newline='\r\n')
            rdr = csv.reader(lines, delimiter=',')
            return list(rdr)
