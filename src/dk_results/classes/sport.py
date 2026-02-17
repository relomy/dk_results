import re
from collections.abc import Iterator
from datetime import date, time


class Sport:
    """Base configuration for a DraftKings DFS sport."""

    sport_name: str = ""
    name: str = ""
    positions: list[str] = []

    sheet_min_entry_fee: int = 25
    keyword: str = "%"

    lineup_range: str | None = None

    dub_min_entry_fee: int = 5
    dub_min_entries: int = 125

    suffixes: list[str] = []
    _compiled_suffix_patterns: list[re.Pattern] | None = None
    _suffix_patterns_cache_key: tuple[str, ...] | None = None

    contest_restraint_day: date | None = None
    contest_restraint_time: time | None = None
    contest_restraint_type_id: int | None = None
    contest_restraint_game_type_id: int | None = None

    allow_optimizer: bool = True
    allow_suffixless_draft_groups: bool = True

    def __init__(self, name: str, lineup_range: str) -> None:
        self.name = name
        self.lineup_range = lineup_range

    @classmethod
    def get_primary_sport(cls) -> str:
        if cls.sport_name:
            return cls.sport_name
        return cls.name

    @classmethod
    def get_suffix_patterns(cls) -> list[re.Pattern]:
        """Return compiled regex patterns for suffix filtering."""
        current_key = tuple(cls.suffixes)
        if cls._compiled_suffix_patterns is None or cls._suffix_patterns_cache_key != current_key:
            cls._compiled_suffix_patterns = [re.compile(pattern) for pattern in cls.suffixes]
            cls._suffix_patterns_cache_key = current_key
        return cls._compiled_suffix_patterns


def _iter_named_sports() -> Iterator[tuple[str, type[Sport]]]:
    for sport_cls in Sport.__subclasses__():
        name = getattr(sport_cls, "name", "")
        if isinstance(name, str) and name:
            yield name, sport_cls


def get_lineup_range(sport_name: str) -> str | None:
    """Return the lineup range for a sport name, if configured."""
    ranges: dict[str, str] = {}
    for name, sport_cls in _iter_named_sports():
        lineup_range = getattr(sport_cls, "lineup_range", None)
        if lineup_range:
            ranges[name] = lineup_range
    return ranges.get(sport_name)


class NFLSport(Sport):
    """NFL sport configuration."""

    name = "NFL"
    sheet_name = "NFL"
    lineup_range = "J3:W999"

    # optimizer
    positions = ["QB", "RB", "RB", "WR", "WR", "WR", "TE", "FLEX", "DST"]
    # positions_count = 9
    # position_constraints = [
    #     ("QB", 1, None),  # 1 or 2 (SFLEX)
    #     ("RB", 2, 3),  # 2 <> 4 (FLEX/SFLEX)
    #     ("WR", 3, 4),  # 3 <> 5 (FLEX/SFLEX)
    #     ("TE", 1, 2),
    #     ("DST", 1, None),
    # ]


class NFLAfternoonSport(Sport):
    """NFL afternoon sport configuration."""

    name = "NFLAfternoon"
    sheet_name = "NFLAfternoon"
    lineup_range = "J3:W999"

    suffixes = [r"\(Afternoon Only\)"]

    dub_min_entry_fee = 25
    dub_min_entries = 125

    sport_name = "NFL"

    # optimizer
    positions = ["QB", "RB", "RB", "WR", "WR", "WR", "TE", "FLEX", "DST"]

    # flags
    allow_suffixless_draft_groups = False


class NFLShowdownSport(Sport):
    """NFL showdown sport configuration."""

    name = "NFLShowdown"
    sheet_name = "NFLShowdown"
    lineup_range = "J3:W999"

    dub_min_entry_fee = 25
    dub_min_entries = 125

    sport_name = "NFL"

    positions = ["CPT", "FLEX"]

    # DK sometimes uses team-vs-team suffixes and sometimes event labels
    # like "(Super Bowl LX)" for the same showdown game type.
    suffixes = [r"\(\w{2,3} @ \w{2,3}\)", r"\([A-Za-z0-9 .'-]+\)"]

    # contest_restraint_time = time(20, 0)
    contest_restraint_game_type_id = 96

    # flags
    allow_optimizer = False
    allow_suffixless_draft_groups = True


class NBASport(Sport):
    """NBA sport configuration."""

    name = "NBA"
    sheet_name = "NBA"

    lineup_range = "J3:W999"
    dub_min_entry_fee = 2
    dub_min_entries = 100

    # optimizer
    positions = ["PG", "SG", "SF", "PF", "C", "G", "F", "UTIL"]
    # positions_count = 8
    # position_constraints = [
    #     ("PG", 1, 2),
    #     ("SG", 1, 2),
    #     ("SF", 1, 2),
    #     ("PF", 1, 2),
    #     ("C", 1, 2),
    # ]


class CFBSport(Sport):
    """CFB sport configuration."""

    name = "CFB"
    sheet_name = "CFB"
    lineup_range = "J3:W999"

    sheet_min_entry_fee = 5
    dub_min_entry_fee = 2
    dub_min_entries = 100

    # optimizer
    positions = ["QB", "RB", "RB", "WR", "WR", "WR", "FLEX", "S-FLEX"]
    positions_count = 8
    position_constraints = [
        ("QB", 1, 2),  # 1 or 2 (SFLEX)
        ("RB", 2, 4),  # 2 <> 4 (FLEX/SFLEX)
        ("WR", 3, 5),  # 3 <> 5 (FLEX/SFLEX)
    ]


class GolfSport(Sport):
    """GOLF/PGA sport configuration."""

    name = "GOLF"
    sheet_name = "GOLF"
    lineup_range = "L8:Z56"

    sheet_min_entry_fee = 10
    dub_min_entry_fee = 2
    dub_min_entries = 100

    suffixes = [r"\(PGA\)", r"\(PGA TOUR\)"]

    lineup_range = "L8:Z56"

    # optimizer
    positions = ["G"]
    positions_count = 6
    position_constraints = [("G", 6, None)]


class PGAMainSport(Sport):
    name = "PGAMain"
    sport_name = "GOLF"
    lineup_range = "L8:X56"

    positions = ["G"]


class PGAWeekendSport(Sport):
    name = "PGAWeekend"
    sport_name = "GOLF"
    lineup_range = "L3:T999"

    positions = ["G"]
    suffixes = [r"\(Weekend PGA TOUR\)"]
    contest_restraint_game_type_id = 33


class PGAShowdownSport(Sport):
    name = "PGAShowdown"
    sport_name = "GOLF"
    lineup_range = "L3:T999"

    positions = ["G"]
    suffixes = [r"\(Round [1-4] PGA TOUR\)", r"\(Round [1-4] TOUR\)"]
    contest_restraint_game_type_id = 87


class WeekendGolfSport(Sport):
    name = "WeekendGolf"
    sport_name = "GOLF"

    positions = ["WG"]


class MLBSport(Sport):
    """MLB sport configuration."""

    name = "MLB"
    sheet_name = "MLB"
    lineup_range = "J3:Z71"

    positions = ["P", "C", "1B", "2B", "3B", "SS", "OF"]


class NascarSport(Sport):
    """NASCAR sport configuration."""

    name = "NAS"
    sheet_name = "NAS"
    lineup_range = "J3:W999"

    positions = ["D"]


class TennisSport(Sport):
    """Tennis sport configuration."""

    name = "TEN"
    sheet_name = "TEN"
    lineup_range = "J3:W999"

    positions = ["P"]


class NHLSport(Sport):
    positions = ["C", "W", "D", "G", "UTIL"]


class XFLSport(Sport):
    name = "XFL"
    lineup_range = "J3:Z56"

    positions = ["QB", "RB", "WR/TE", "WR/TE", "FLEX", "FLEX", "DST"]


class LOLSport(Sport):
    name = "LOL"
    lineup_range = "J3:W999"

    positions = ["CPT", "TOP", "JNG", "MID", "ADC", "SUP", "TEAM"]


class MMASport(Sport):
    name = "MMA"
    lineup_range = "J3:W999"

    positions = ["F"]


class USFLSport(Sport):
    name = "USFL"
    lineup_range = "J3:W999"

    positions = ["QB", "RB", "WR/TE", "WR/TE", "FLEX", "FLEX", "DST"]
