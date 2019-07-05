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


class Results(object):
    """Create a Results object which contains the results for a given DraftKings contest."""

    def __init__(self, sport, contest_id, salary_csv_fn, logger=None):
        self.logger = logger or logging.getLogger(__name__)

        self.sport = sport
        self.contest_id = contest_id
        self.players = {}
        self.users = []

        # if there's no salary file specified, use the sport/day for the filename
        if not salary_csv_fn:
            salary_csv_fn = "DKSalaries_{}_{}.csv".format(
                self.sport, datetime.datetime.now().strftime('%A'))

        self.parse_salary_csv(salary_csv_fn)

        self.vips = ['aplewandowski', 'FlyntCoal', 'Cubbiesftw23', 'Mcoleman1902',
                     'cglenn91', 'Notorious', 'Bra3105', 'ChipotleAddict']
        self.vip_list = []

        contest_fn = 'contest-standings-73990354.csv'

        # this pulls the DK users and updates the players stats
        self.parse_contest_standings_csv(contest_fn)

        # for player in self.complete_players:
        #     self.logger.debug(player)

        for vip in self.vip_list:
            self.logger.debug("VIP: {}".format(vip))
            temp = self.parse_lineup_string(vip.lineup_str)
            self.logger.debug(temp)

        # for k, v in self.players_dict.items():
        #     self.logger.debug("{}: {}".format(k, v))

    def parse_lineup_string(self, lineup_str):
        lineup_list_of_players = []
        splt = lineup_str.split(' ')
        positions = ['G']
        # list comp for indicies of positions in splt
        indices = [i for i, pos in enumerate(splt) if pos in positions]
        # list comp for ending indices in splt. for splicing, the second argument is exclusive
        end_indices = [indices[i] for i in range(1, len(indices))]
        # append size of splt as last index
        end_indices.append(len(splt))
        self.logger.debug("indices: {}".format(indices))
        self.logger.debug("end_indices: {}".format(end_indices))
        for i, index in enumerate(indices):
            pos = splt[index]

            s = slice(index + 1, end_indices[i])
            name = splt[s]
            if name != 'LOCKED':
                name = ' '.join(name)

                # ensure name doesn't have any weird characters
                name = self.strip_accents(name)

                if name in self.players:
                    lineup_list_of_players.append(self.players[name])

        return lineup_list_of_players

    def strip_accents(self, name):
        """Strip accents from a given string and replace with letters without accents."""
        return ''.join(c for c in unicodedata.normalize('NFD', name)
                       if unicodedata.category(c) != 'Mn')

    def parse_salary_csv(self, fn):
        """Parse CSV containing players and salary information."""
        with open(fn, mode='r') as f:
            cr = csv.reader(f, delimiter=',')
            slate_list = list(cr)

            for row in slate_list[1:]:  # [1:] to skip header
                if len(row) < 2:
                    continue
                # TODO: might use roster_pos in the future
                pos, _, name, _, roster_pos, salary, game_info, team_abbv, appg = row
                # self.players.append(Player(name, pos, salary, game_info, team_abbv))
                self.players[name] = Player(name, pos, salary, game_info, team_abbv)

    def parse_contest_standings_csv(self, fn):
        """Parse CSV containing contest standings and player ownership."""
        list = self.load_standings(fn)
        # create a copy of player list
        # player_list = self.players
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
                name = self.strip_accents(name)

                self.players[name].update_stats(pos, perc, fpts)

                # for i, player in enumerate(player_list):
                #     if name == player.name:
                #         self.logger.debug(
                #             "name {} MATCHES player.name {}!".format(name, player.name))
                #         # update stats for player
                #         player.update_stats(pos, perc, fpts)
                #         # update complete_players list
                #         self.complete_players.append(player)
                #         # delete player from copy of list to speed up search
                #         del(player_list[i])
                #         break

    def load_standings(self, fn):
        """Load standings CSV and return list."""
        with open(fn, 'rb') as csvfile:
            lines = io.TextIOWrapper(csvfile, encoding='utf-8', newline='\r\n')
            rdr = csv.reader(lines, delimiter=',')
            return list(rdr)
