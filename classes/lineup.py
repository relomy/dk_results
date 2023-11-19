import copy
import unicodedata

from classes.sport import Sport

from .player import Player


class Lineup:
    """A representation of a list of Players"""

    def __init__(self, sport_obj: Sport, players, lineup_str):
        self.sport_obj = sport_obj
        self.players = players

        self.lineup = self.parse_lineup_string(lineup_str)

    def parse_lineup_string(self, lineup_str) -> list:
        """Parse lineup_str and return list of Players."""
        player_list = []

        splt = lineup_str.split(" ")

        # list comp for indicies of positions in splt
        indices = [i for i, pos in enumerate(splt) if pos in self.sport_obj.positions]

        # list comp for ending indices in splt. for splicing, the second argument is exclusive
        end_indices = [indices[i] for i in range(1, len(indices))]

        # append size of splt as last index
        end_indices.append(len(splt))

        for i, index in enumerate(indices):
            name_slice = slice(index + 1, end_indices[i])
            pos_slice = slice(index, index + 1)
            name = splt[name_slice]
            position = splt[pos_slice][0]

            if "LOCKED" in name:
                name = "LOCKED 🔒"
                player_list.append(Player(name, position, None, 0, None, None))
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
            player_list,
            key=lambda x: (self.sport_obj.positions.index(x.pos), x.name),
        )

        return sorted_list

    def strip_accents_and_periods(self, name):
        """Strip accents from a given string and replace with letters without accents."""
        return "".join(
            c
            for c in unicodedata.normalize("NFD", name)
            if unicodedata.category(c) != "Mn"
        )

    def __str__(self):
        str = ""

        for player in self.lineup:
            str += f"{player.pos} {player.name} "

        return str
