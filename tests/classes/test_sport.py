from classes.sport import Sport


def test_sport_init_sets_name_and_range():
    sport = Sport("NBA", "A1:B2")
    assert sport.name == "NBA"
    assert sport.lineup_range == "A1:B2"


def test_get_primary_sport_prefers_sport_name():
    class DummySport(Sport):
        name = "NBA"
        sport_name = "GOLF"

    class DummySport2(Sport):
        name = "NBA"
        sport_name = ""

    assert DummySport.get_primary_sport() == "GOLF"
    assert DummySport2.get_primary_sport() == "NBA"


def test_get_suffix_patterns_compiles_and_refreshes():
    class DummySuffixSport(Sport):
        suffixes = [r"\(Main\)"]

    patterns = DummySuffixSport.get_suffix_patterns()
    assert patterns[0].pattern == r"\(Main\)"

    DummySuffixSport.suffixes = [r"\(Late\)"]
    patterns2 = DummySuffixSport.get_suffix_patterns()
    assert patterns2[0].pattern == r"\(Late\)"
