from classes.lineup import Lineup, parse_lineup_string
from classes.player import Player


class DummySport:
    positions = ["RB", "WR", "FLEX"]


def test_parse_lineup_string_handles_position_swap():
    players = {
        "John Doe": Player("John Doe", "RB", "RB", 5000, "AAA@BBB 7:00PM", "AAA")
    }

    lineup = parse_lineup_string(DummySport, players, "FLEX John Doe")

    assert lineup[0].pos == "FLEX"
    assert players["John Doe"].pos == "RB"


def test_lineup_str_formats_players():
    players = {
        "John Doe": Player("John Doe", "RB", "RB", 5000, "AAA@BBB 7:00PM", "AAA")
    }

    lineup = Lineup(DummySport, players, "RB John Doe")
    assert str(lineup) == "RB John Doe "
