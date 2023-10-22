class Sport:
    """An object to represent a DFS sport from DraftKings.

    Args:
        object (_type_): _description_
    """

    sport_name = None
    name = None

    sheet_min_entry_fee = 25
    keyword = "%"

    dub_min_entry_fee = 5
    dub_min_entries = 125

    suffixes = []

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
    lineup_range = "J3:V66"

    # optimizer
    positions = ["QB", "RB", "RB", "WR", "WR", "WR", "TE", "FLEX"]
    positions_count = 9
    position_constraints = [
        ("QB", 1, None),  # 1 or 2 (SFLEX)
        ("RB", 2, 3),  # 2 <> 4 (FLEX/SFLEX)
        ("WR", 3, 4),  # 3 <> 5 (FLEX/SFLEX)
        ("TE", 1, 2),
        ("DST", 1, None),
    ]


class NFLShowdownSport(Sport):
    """NFL

    Args:
        Sport (_type_): _description_
    """

    name = "NFLShowdown"
    sheet_name = "NFLShowdown"
    lineup_range = "J3:V66"

    sport_name = "NFL"

    suffixes = ["(Primetime)"]


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

    suffixes = ["(PGA)", "(PGA TOUR)"]

    lineup_range = "L8:Z56"

    # optimizer
    positions = ["G"]
    positions_count = 6
    position_constraints = [("G", 6, None)]


class MLBSport(Sport):
    """MLB

    Args:
        Sport (_type_): _description_
    """

    name = "MLB"
    sheet_name = "MLB"
    lineup_range = "J3:V71"


class NascarSport(Sport):
    """NASCAR

    Args:
        Sport (_type_): _description_
    """

    name = "NAS"
    sheet_name = "NAS"
    lineup_range = "J3:V61"


class TennisSport(Sport):
    """Tennis

    Args:
        Sport (_type_): _description_
    """

    name = "TEN"
    sheet_name = "TEN"
    lineup_range = "J3:V61"
