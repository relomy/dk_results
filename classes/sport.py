from datetime import time


class Sport:
    """An object to represent a DFS sport from DraftKings.

    Args:
        object (_type_): _description_
    """

    sport_name = None
    name = None
    positions = []

    sheet_min_entry_fee = 25
    keyword = "%"

    dub_min_entry_fee = 5
    dub_min_entries = 125

    suffixes = []

    contest_restraint_day = None
    contest_restraint_time = None
    contest_restraint_type_id = None

    def __init__(self, name, lineup_range) -> None:
        self.name = name
        self.lineup_range = lineup_range

    @classmethod
    def get_primary_sport(cls) -> str:
        if cls.sport_name is not None:
            return cls.sport_name

        return cls.name


class NFLSport(Sport):
    """NFL

    Args:
        Sport (_type_): _description_
    """

    name = "NFL"
    sheet_name = "NFL"
    lineup_range = "J3:V99"

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


class NFLShowdownSport(Sport):
    """NFL

    Args:
        Sport (_type_): _description_
    """

    name = "NFLShowdown"
    sheet_name = "NFLShowdown"
    lineup_range = "J3:V66"

    dub_min_entry_fee = 25
    dub_min_entries = 125

    sport_name = "NFL"

    positions = ["CPT", "FLEX"]

    suffixes = [r"\(\w{2,3} vs \w{2,3}\)"]

    contest_restraint_time = time(20, 0)


class NBASport(Sport):
    """NBA

    Args:
        Sport (_type_): _description_
    """

    name = "NBA"
    sheet_name = "NBA"

    lineup_range = "J3:V66"
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
    """CFB

    Args:
        Sport (_type_): _description_
    """

    name = "CFB"
    sheet_name = "CFB"
    lineup_range = "J3:V61"

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
    """GOLF/PGA

    Args:
        Sport (_type_): _description_
    """

    name = "GOLF"
    sheet_name = "GOLF"
    lineup_range = "L8:Z56"

    dub_min_entry_fee = 2
    dub_min_entries = 100

    suffixes = [r"\(PGA\)", r"\(PGA TOUR\)"]

    lineup_range = "L8:Z56"

    # optimizer
    positions = ["G"]
    positions_count = 6
    position_constraints = [("G", 6, None)]


class WeekendGolfSport(Sport):
    name = "WeekendGolf"
    sport_name = "GOLF"

    positions = ["WG"]


class MLBSport(Sport):
    """MLB

    Args:
        Sport (_type_): _description_
    """

    name = "MLB"
    sheet_name = "MLB"
    lineup_range = "J3:V71"

    positions = ["P", "C", "1B", "2B", "3B", "SS", "OF"]


class NascarSport(Sport):
    """NASCAR

    Args:
        Sport (_type_): _description_
    """

    name = "NAS"
    sheet_name = "NAS"
    lineup_range = "J3:V61"

    positions = ["D"]


class TennisSport(Sport):
    """Tennis

    Args:
        Sport (_type_): _description_
    """

    name = "TEN"
    sheet_name = "TEN"
    lineup_range = "J3:V61"

    positions = ["P"]


class NHLSport(Sport):
    positions = ["C", "W", "D", "G", "UTIL"]


class XFLSport(Sport):
    positions = ["QB", "RB", "WR/TE", "WR/TE", "FLEX", "FLEX", "DST"]


class LOLSport(Sport):
    positions = ["CPT", "TOP", "JNG", "MID", "ADC", "SUP", "TEAM"]


class MMASport(Sport):
    positions = ["F"]
