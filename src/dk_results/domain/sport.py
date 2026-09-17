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

    # Suffix constraint for this sport's draft groups:
    #   None                -> unconstrained: any suffix, or none, passes
    #   ()                  -> must be suffixless
    #   (p1, p2, ...)       -> suffix must match one of these patterns; suffixless rejected
    #   (None, p1, p2, ...) -> suffixless OR one of these patterns
    suffixes: tuple[str | None, ...] | None = None
    _compiled_suffix_patterns: tuple[re.Pattern[str], ...] | None = None
    _suffix_patterns_cache_key: tuple[str | None, ...] | None = None

    contest_restraint_day: date | None = None
    contest_restraint_time: time | None = None
    contest_restraint_type_id: int | None = None
    contest_restraint_game_type_id: int | None = None

    # Opt-in: a sport is optimized only once its ``positions`` layout is
    # confirmed against a real DraftKings salary file (see ADR-0005). An
    # unconfirmed sport stays off rather than risk shipping a wrong lineup.
    allow_optimizer: bool = False

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
        """Return compiled regex patterns for suffix filtering, excluding the suffixless sentinel."""
        current_key = cls.suffixes
        if cls._compiled_suffix_patterns is None or cls._suffix_patterns_cache_key != current_key:
            patterns = filter(None, current_key or ())
            cls._compiled_suffix_patterns = tuple(re.compile(pattern) for pattern in patterns)
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

    # Classic only — excludes NFLShowdown (96) and other special game types
    # from the classic NFL draft-group pool. Without this, a Showdown draft
    # group could be selected as the live "NFL" contest and parsed with
    # classic QB/RB/WR/TE/FLEX/DST slots against Showdown's CPT/FLEX
    # layout, producing spurious "Unresolved lineup slot FLEX: <DST>"
    # errors for entrants who (legitimately, in Showdown) put a team
    # defense in FLEX.
    contest_restraint_game_type_id = 1

    # Suffixless only — excludes the Afternoon/Thu-Mon/Sun-Mon/Early/Turbo
    # suffixed Classic draft groups from the classic NFL pool. Only
    # (Afternoon Only) has a dedicated sibling sport (NFLAfternoonSport);
    # the others are not tracked under any sport yet.
    suffixes = ()

    # optimizer
    positions = ("QB", "RB", "RB", "WR", "WR", "WR", "TE", "FLEX", "DST")
    allow_optimizer = True


class NFLAfternoonSport(Sport):
    """NFL afternoon sport configuration."""

    name = "NFLAfternoon"
    sheet_name = "NFLAfternoon"
    lineup_range = "J3:W999"

    suffixes = (r"\(Afternoon Only\)",)

    # Classic only — (Afternoon Only) also appears on Tiers (51) and Snake
    # (189) draft groups; without this restraint those would be misrouted
    # into the Afternoon sheet with the wrong lineup shape.
    contest_restraint_game_type_id = 1

    dub_min_entry_fee = 25
    dub_min_entries = 125

    draftkings_sport = "NFL"

    # optimizer
    positions = ("QB", "RB", "RB", "WR", "WR", "WR", "TE", "FLEX", "DST")


class NFLShowdownSport(Sport):
    """NFL showdown sport configuration."""

    name = "NFLShowdown"
    sheet_name = "NFLShowdown"
    lineup_range = "J3:W999"

    dub_min_entry_fee = 25
    dub_min_entries = 125

    draftkings_sport = "NFL"

    # Layout confirmed from a real standings file: 1 CPT + 5 FLEX. Optimizer
    # stays off (inherits the opt-in default): the CPT slot scores and costs 1.5x,
    # which the flat per-player solver does not yet model, so a size-correct
    # lineup would still misvalue the captain. See ADR-0005.
    positions = ("CPT", "FLEX", "FLEX", "FLEX", "FLEX", "FLEX")

    # DK sometimes uses team-vs-team suffixes and sometimes event labels
    # like "(Super Bowl LX)" for the same showdown game type; suffixless is
    # also allowed.
    suffixes = (None, r"\(\w{2,3} @ \w{2,3}\)", r"\([A-Za-z0-9 .'-]+\)")

    # DraftKings tags one "Featured" Showdown per game window, not just
    # primetime — a Sunday early (1:00) and late (4:05/4:25) window each get
    # their own Featured Showdown with an ordinary (TEAM @ TEAM) suffix,
    # indistinguishable from Thu/Sun/Mon night by suffix or game type alone.
    # Confirmed via live data pulled 2026-09-17. Regular-season primetime
    # games kick off ~20:15-20:20 ET, but the Super Bowl kicks off ~18:30 ET
    # (see test_filter_draft_groups_nfl_showdown_super_bowl_suffix) — a 6:00
    # PM floor keeps every single-game primetime/marquee window while still
    # excluding every standard Sunday day window (never later than ~16:25).
    contest_restraint_time = time(18, 0)
    contest_restraint_game_type_id = 96


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

    # optimizer — layout confirmed from a real standings file: six WG slots.
    positions = ("WG", "WG", "WG", "WG", "WG", "WG")
    allow_optimizer = True


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
