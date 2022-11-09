import copy
import unicodedata

from .player import Player


class Lineup:
    """A representation of a list of Players"""

    # dict of positions for each sport
    POSITIONS = {
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
        "USFL": ["QB", "RB", "WR/TE", "WR/TE", "FLEX", "FLEX", "DST"],
    }

    def __init__(self, sport, players, lineup_str):
        self.sport = sport
        self.players = players

        self.lineup = self.parse_lineup_string(lineup_str)

    def parse_lineup_string(self, lineup_str) -> list:
        """Parse lineup_str and return list of Players."""
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

    def __str__(self):
        str = ""

        for player in self.lineup:
            str += f"{player.pos} {player.name} "

        return str
