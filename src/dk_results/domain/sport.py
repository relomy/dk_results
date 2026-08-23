import re
from collections.abc import Iterator, Mapping
from datetime import date, time
from types import MappingProxyType


class Sport:
    """Base class-level configuration for a DraftKings DFS sport variant.

    ``name`` is the canonical application-level variant identity (for example,
    ``NFLShowdown``); ``draftkings_sport`` is the lobby/API sport code (for
    example, ``NFL``). When the latter is omitted, the variant name is used.
    """

    draftkings_sport: str = ""
    name: str = ""
    positions: tuple[str, ...] = ()

    salary_cap: int = 50000

    sheet_min_entry_fee: int = 25
    keyword: str = "%"

    lineup_range: str | None = None

    dub_min_entry_fee: int = 5
    dub_min_entries: int = 125

    suffixes: tuple[str, ...] = ()
    _compiled_suffix_patterns: tuple[re.Pattern[str], ...] | None = None
    _suffix_patterns_cache_key: tuple[str, ...] | None = None

    contest_restraint_day: date | None = None
    contest_restraint_time: time | None = None
    contest_restraint_type_id: int | None = None
    contest_restraint_game_type_id: int | None = None

    # Opt-in: a sport is optimized only once its ``positions`` layout is
    # confirmed against a real DraftKings salary file (see ADR-0005). An
    # unconfirmed sport stays off rather than risk shipping a wrong lineup.
    allow_optimizer: bool = False
    allow_suffixless_draft_groups: bool = True

    @classmethod
    def get_draftkings_sport(cls) -> str:
        if cls.draftkings_sport:
            return cls.draftkings_sport
        return cls.name

    @classmethod
    def get_primary_sport(cls) -> str:
        return cls.get_draftkings_sport()

    @classmethod
    def get_suffix_patterns(cls) -> tuple[re.Pattern[str], ...]:
        """Return compiled regex patterns for suffix filtering."""
        current_key = tuple(cls.suffixes)
        if cls._compiled_suffix_patterns is None or cls._suffix_patterns_cache_key != current_key:
            cls._compiled_suffix_patterns = tuple(re.compile(pattern) for pattern in cls.suffixes)
            cls._suffix_patterns_cache_key = current_key
        return cls._compiled_suffix_patterns


def _build_sport_registry(sport_classes: Iterator[type[Sport]]) -> Mapping[str, type[Sport]]:
    registry: dict[str, type[Sport]] = {}
    for sport_cls in sport_classes:
        name = getattr(sport_cls, "name", None)
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"Sport class {sport_cls.__name__} must define a non-empty string name")
        normalized_name = name.casefold()
        if any(existing.casefold() == normalized_name for existing in registry):
            raise ValueError(f"Duplicate sport name: {name}")
        registry[name] = sport_cls
    return MappingProxyType(dict(sorted(registry.items())))


def _sport_registry() -> Mapping[str, type[Sport]]:
    return SPORT_REGISTRY


def iter_sports() -> tuple[type[Sport], ...]:
    """Return built-in sport variants in canonical-name order."""
    return tuple(_sport_registry().values())


def get_sport_choices() -> Mapping[str, type[Sport]]:
    """Return the read-only canonical sport-variant registry."""
    return _sport_registry()


def get_sport(name: str) -> type[Sport] | None:
    """Return a sport class for a normalized name, or ``None`` if unknown."""
    if not isinstance(name, str):
        return None
    normalized = name.strip().casefold()
    return next((sport_cls for key, sport_cls in _sport_registry().items() if key.casefold() == normalized), None)


def require_sport(name: str) -> type[Sport]:
    """Return a sport class or raise a clear error for an unknown name."""
    sport_cls = get_sport(name)
    if sport_cls is None:
        raise ValueError(f"Unknown sport: {name}")
    return sport_cls


def get_lineup_range(sport_name: str) -> str | None:
    """Return the lineup range for a sport name, if configured."""
    sport_cls = get_sport(sport_name)
    return sport_cls.lineup_range if sport_cls else None


class NFLSport(Sport):
    """NFL sport configuration."""

    name = "NFL"
    sheet_name = "NFL"
    lineup_range = "J3:W999"

    # optimizer
    positions = ("QB", "RB", "RB", "WR", "WR", "WR", "TE", "FLEX", "DST")
    allow_optimizer = True


class NFLAfternoonSport(Sport):
    """NFL afternoon sport configuration."""

    name = "NFLAfternoon"
    sheet_name = "NFLAfternoon"
    lineup_range = "J3:W999"

    suffixes = (r"\(Afternoon Only\)",)

    dub_min_entry_fee = 25
    dub_min_entries = 125

    draftkings_sport = "NFL"

    # optimizer
    positions = ("QB", "RB", "RB", "WR", "WR", "WR", "TE", "FLEX", "DST")

    # flags
    allow_suffixless_draft_groups = False


class NFLShowdownSport(Sport):
    """NFL showdown sport configuration."""

    name = "NFLShowdown"
    sheet_name = "NFLShowdown"
    lineup_range = "J3:W999"

    dub_min_entry_fee = 25
    dub_min_entries = 125

    draftkings_sport = "NFL"

    # Showdown roster differs from the classic NFL layout; optimizer stays off
    # (inherits the opt-in default) until confirmed against a real file.
    positions = ("CPT", "FLEX")

    # DK sometimes uses team-vs-team suffixes and sometimes event labels
    # like "(Super Bowl LX)" for the same showdown game type.
    suffixes = (r"\(\w{2,3} @ \w{2,3}\)", r"\([A-Za-z0-9 .'-]+\)")

    # contest_restraint_time = time(20, 0)
    contest_restraint_game_type_id = 96

    # flags
    allow_suffixless_draft_groups = True


class NBASport(Sport):
    """NBA sport configuration."""

    name = "NBA"
    sheet_name = "NBA"

    lineup_range = "J3:W999"
    dub_min_entry_fee = 2
    dub_min_entries = 100

    # optimizer
    positions = ("PG", "SG", "SF", "PF", "C", "G", "F", "UTIL")
    allow_optimizer = True


class CFBSport(Sport):
    """CFB sport configuration."""

    name = "CFB"
    sheet_name = "CFB"
    lineup_range = "J3:W999"

    sheet_min_entry_fee = 5
    dub_min_entry_fee = 2
    dub_min_entries = 100

    # optimizer — layout confirmed from a real standings file (QB, RB, RB, WR,
    # WR, WR, FLEX, S-FLEX); DraftKings encodes FLEX / S-FLEX eligibility in
    # each player's roster_pos.
    positions = ("QB", "RB", "RB", "WR", "WR", "WR", "FLEX", "S-FLEX")
    allow_optimizer = True


class GolfSport(Sport):
    """GOLF/PGA sport configuration."""

    name = "GOLF"
    sheet_name = "GOLF"
    lineup_range = "L8:Z56"

    sheet_min_entry_fee = 10
    dub_min_entry_fee = 2
    dub_min_entries = 100

    suffixes = (r"\(PGA\)", r"\(PGA TOUR\)")

    lineup_range = "L8:Z56"

    # optimizer — a DraftKings golf roster is six G slots.
    positions = ("G", "G", "G", "G", "G", "G")
    allow_optimizer = True


class PGAMainSport(Sport):
    name = "PGAMain"
    draftkings_sport = "GOLF"
    lineup_range = "L8:X56"

    positions = ("G",)


class PGAWeekendSport(Sport):
    name = "PGAWeekend"
    draftkings_sport = "GOLF"
    lineup_range = "L3:T999"

    positions = ("G",)
    suffixes = (r"\(Weekend PGA TOUR\)",)
    contest_restraint_game_type_id = 33


class PGAShowdownSport(Sport):
    name = "PGAShowdown"
    draftkings_sport = "GOLF"
    lineup_range = "L3:T999"

    positions = ("G",)
    suffixes = (r"\(Round [1-4] PGA TOUR\)", r"\(Round [1-4] TOUR\)")
    contest_restraint_game_type_id = 87


class WeekendGolfSport(Sport):
    name = "WeekendGolf"
    draftkings_sport = "GOLF"

    positions = ("WG",)


class MLBSport(Sport):
    """MLB sport configuration."""

    name = "MLB"
    sheet_name = "MLB"
    lineup_range = "J3:Z71"

    # optimizer — layout confirmed from a real standings file: 2 P, 1 each of
    # C/1B/2B/3B/SS, 3 OF = 10 slots.
    positions = ("P", "P", "C", "1B", "2B", "3B", "SS", "OF", "OF", "OF")
    allow_optimizer = True


class NascarSport(Sport):
    """NASCAR sport configuration."""

    name = "NAS"
    sheet_name = "NAS"
    lineup_range = "J3:W999"

    positions = ("D",)


class TennisSport(Sport):
    """Tennis sport configuration."""

    name = "TEN"
    sheet_name = "TEN"
    lineup_range = "J3:W999"

    positions = ("P",)


class NHLSport(Sport):
    name = "NHL"
    sheet_name = "NHL"
    lineup_range = "J3:W999"
    positions = ("C", "W", "D", "G", "UTIL")


class XFLSport(Sport):
    name = "XFL"
    lineup_range = "J3:Z56"

    positions = ("QB", "RB", "WR/TE", "WR/TE", "FLEX", "FLEX", "DST")


class LOLSport(Sport):
    name = "LOL"
    lineup_range = "J3:W999"

    positions = ("CPT", "TOP", "JNG", "MID", "ADC", "SUP", "TEAM")


class MMASport(Sport):
    name = "MMA"
    lineup_range = "J3:W999"

    positions = ("F",)


class USFLSport(Sport):
    name = "USFL"
    lineup_range = "J3:W999"

    positions = ("QB", "RB", "WR/TE", "WR/TE", "FLEX", "FLEX", "DST")


class SOCSport(Sport):
    name = "SOC"
    lineup_range = "J3:W999"

    dub_min_entries = 50
    contest_restraint_game_type_id = 122

    # optimizer — layout confirmed from a real standings file: 2 F, 2 M, 2 D,
    # 1 GK, 1 UTIL = 8 slots.
    positions = ("F", "F", "M", "M", "D", "D", "GK", "UTIL")
    allow_optimizer = True


class SOCShowdownSport(Sport):
    name = "SOCShowdown"
    draftkings_sport = "SOC"
    lineup_range = "J3:W999"

    contest_restraint_game_type_id = 123

    # Showdown roster differs from the classic SOC layout; optimizer stays off
    # (inherits the opt-in default) until confirmed against a real file.
    positions = ("CPT", "FLEX")


SPORT_REGISTRY = _build_sport_registry(iter(Sport.__subclasses__()))
