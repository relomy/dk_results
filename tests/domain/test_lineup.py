import pytest

from dk_results.domain.lineup import Lineup, LineupParseError, LockedSlot, parse_lineup_string
from dk_results.domain.player import Player


class DummySport:
    positions = ["RB", "WR", "FLEX"]


def test_parse_lineup_string_handles_position_swap():
    players = {"John Doe": Player("John Doe", "RB", "RB", 5000, "AAA@BBB 7:00PM", "AAA")}

    lineup = parse_lineup_string(DummySport, players, "FLEX John Doe")

    assert lineup[0].pos == "FLEX"
    assert players["John Doe"].pos == "RB"


def test_lineup_str_formats_players():
    players = {"John Doe": Player("John Doe", "RB", "RB", 5000, "AAA@BBB 7:00PM", "AAA")}

    lineup = Lineup(DummySport, players, "RB John Doe")
    assert str(lineup) == "RB John Doe "


def test_parse_lineup_string_preserves_locked_slot():
    lineup = parse_lineup_string(DummySport, {}, "RB LOCKED")

    assert lineup == [LockedSlot("RB")]
    assert lineup[0].name == "LOCKED 🔒"
    assert lineup[0].salary == 0


def test_parse_lineup_string_rejects_unknown_player_with_position_and_name():
    with pytest.raises(LineupParseError, match=r"WR.*Unknown Player"):
        parse_lineup_string(DummySport, {}, "WR Unknown Player")


def test_parse_lineup_string_does_not_return_partial_lineup_for_unknown_player():
    with pytest.raises(LineupParseError, match="Unknown Player"):
        parse_lineup_string(
            DummySport,
            {"John Doe": Player("John Doe", "RB", "RB", 5000, "", "")},
            "RB John Doe WR Unknown Player",
        )
