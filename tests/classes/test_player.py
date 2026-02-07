from classes.player import Player


def test_get_matchup_info_status_returns_raw():
    player = Player("Name", "RB", "RB", 5000, "Final", "AAA")
    assert player.get_matchup_info() == "Final"


class WeirdStr(str):
    def __contains__(self, item):
        return item == "@"


def test_get_matchup_info_status_with_at_sign():
    game_info = WeirdStr("Final")
    player = Player("Name", "RB", "RB", 5000, game_info, "AAA")

    assert player.get_matchup_info() == "Final"
