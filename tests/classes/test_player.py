from classes.player import Player


def test_get_matchup_info_status_returns_raw():
    player = Player("Name", "RB", "RB", 5000, "Final", "AAA")
    assert player.get_matchup_info() == "Final"
