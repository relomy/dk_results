import pytest

from dk_results.domain.sport import (
    NFLShowdownSport,
    NHLSport,
    Sport,
    _build_sport_registry,
    get_lineup_range,
    get_sport,
    get_sport_choices,
    iter_sports,
    require_sport,
)


def test_sport_is_class_level_configuration():
    assert "__init__" not in Sport.__dict__
    assert NFLShowdownSport.name == "NFLShowdown"
    assert NFLShowdownSport.get_draftkings_sport() == "NFL"


def test_registry_normalizes_lookup_and_preserves_canonical_names():
    assert get_sport("  nflshowdown ") is NFLShowdownSport
    assert require_sport("nFl") is get_sport("NFL")
    assert [sport.name for sport in iter_sports()] == sorted(sport.name for sport in iter_sports())


def test_registry_contains_complete_nhl_definition_and_lineup_lookup():
    assert get_sport("NHL") is NHLSport
    assert get_lineup_range(" nhl ") == "J3:W999"


def test_registry_unknown_lookup_is_optional_or_strict():
    assert get_sport("unknown") is None
    with pytest.raises(ValueError, match="Unknown sport: unknown"):
        require_sport("unknown")


def test_registry_choices_are_read_only():
    choices = get_sport_choices()
    assert choices is get_sport_choices()
    with pytest.raises(TypeError):
        choices["NEW"] = NFLShowdownSport  # type: ignore[index]


def test_registry_rejects_duplicate_and_invalid_names():
    class First(Sport):
        name = "Duplicate"

    class Second(Sport):
        name = "duplicate"

    class Invalid(Sport):
        name = ""

    with pytest.raises(ValueError, match="Duplicate sport name"):
        _build_sport_registry(iter((First, Second)))
    with pytest.raises(ValueError, match="must define a non-empty string name"):
        _build_sport_registry(iter((Invalid,)))


def test_get_primary_sport_prefers_draftkings_override_and_falls_back_to_name():
    class GolfVariant(Sport):
        name = "GolfVariant"
        draftkings_sport = "GOLF"

    class Basketball(Sport):
        name = "NBA"

    assert GolfVariant.get_primary_sport() == "GOLF"
    assert Basketball.get_primary_sport() == "NBA"


def test_fixed_sport_configuration_collections_are_tuples():
    from dk_results.domain.sport import CFBSport, GolfSport

    assert isinstance(CFBSport.positions, tuple)
    assert isinstance(CFBSport.position_constraints, tuple)
    assert isinstance(GolfSport.position_constraints, tuple)


def test_get_suffix_patterns_compiles_and_refreshes_as_immutable_tuple():
    class DummySuffixSport(Sport):
        suffixes = (r"\(Main\)",)

    patterns = DummySuffixSport.get_suffix_patterns()
    assert patterns[0].pattern == r"\(Main\)"
    assert isinstance(patterns, tuple)

    DummySuffixSport.suffixes = (r"\(Late\)",)
    patterns2 = DummySuffixSport.get_suffix_patterns()
    assert patterns2[0].pattern == r"\(Late\)"
