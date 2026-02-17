import copy
import unicodedata
from typing import Type

from dk_results.classes.sport import Sport

from .player import Player


def normalize_name(name: str) -> str:
    """Strip accents from a given string and replace with letters without accents."""
    return "".join(
        c for c in unicodedata.normalize("NFD", name) if unicodedata.category(c) != "Mn"
    )


def parse_lineup_string(
    sport_obj: Sport | Type[Sport],
    players: dict[str, Player],
    lineup_str: str,
) -> list[Player]:
    """Parse lineup_str and return list of Players."""
    player_list: list[Player] = []

    splt = lineup_str.split(" ")

    # list comp for indices of positions in splt
    indices = [i for i, pos in enumerate(splt) if pos in sport_obj.positions]

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
            player_list.append(Player(name, position, None, 0, "", ""))
        else:
            # self.logger.debug(name)
            name = " ".join(name)

            # ensure name doesn't have any weird characters
            name = normalize_name(name)

            if name in players:
                # check if position is different (FLEX, etc.)
                if position != players[name].pos:
                    # create copy of local Player to update player's position for the sheet
                    player_copy = copy.deepcopy(players[name])
                    player_copy.pos = position
                    player_list.append(player_copy)
                else:
                    player_list.append(players[name])

    # sort by DraftKings roster order (RB, RB, WR, WR, etc.), then name
    sorted_list = sorted(
        player_list,
        key=lambda x: (sport_obj.positions.index(x.pos), x.name),
    )

    return sorted_list


class Lineup:
    """A representation of a list of Players"""

    def __init__(
        self, sport_obj: Sport | Type[Sport], players: dict[str, Player], lineup_str: str
    ) -> None:
        self.sport_obj = sport_obj
        self.players = players

        self.lineup = parse_lineup_string(self.sport_obj, self.players, lineup_str)

    def __str__(self) -> str:
        str = ""

        for player in self.lineup:
            str += f"{player.pos} {player.name} "

        return str
