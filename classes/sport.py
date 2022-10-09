# LINEUP_RANGES = {
#         "NBA": "J3:V61",
#         "CFB": "J3:V61",
#         "NFL": "J3:V66",
#         "GOLF": "L8:Z56",
#         "PGAMain": "L8:X56",
#         "PGAWeekend": "L3:Q41",
#         "PGAShowdown": "L3:Q41",
#         "TEN": "J3:V61",
#         "MLB": "J3:V71",
#         "XFL": "J3:V56",
#         "MMA": "J3:V61",
#         "LOL": "J3:V61",
#         "NAS": "J3:V61",
#         "USFL": "J3:V66",
#     }


class Sport:
    """An object to represent a DFS sport from DraftKings.

    Args:
        object (_type_): _description_
    """

    min_entry_fee = 25
    keyword = "%"

    def __init__(self, name, lineup_range) -> None:
        self.name = name
        self.lineup_range = lineup_range


class NFLSport(Sport):
    """NFL

    Args:
        Sport (_type_): _description_
    """

    name = "NFL"
    lineup_range = "J3:V66"


class NBASport(Sport):
    """NBA

    Args:
        Sport (_type_): _description_
    """

    name = "NBA"
    lineup_range = "J3:V66"


class CFBSport(Sport):
    """CFB

    Args:
        Sport (_type_): _description_
    """

    name = "CFB"
    lineup_range = "J3:V61"

    min_entry_fee = 5


class GolfSport(Sport):
    """GOLF/PGA

    Args:
        Sport (_type_): _description_
    """

    name = "GOLF"
    lineup_range = "L8:Z56"


class MLBSport(Sport):
    """MLB

    Args:
        Sport (_type_): _description_
    """

    name = "MLB"
    lineup_range = "J3:V71"


class NascarSport(Sport):
    """NASCAR

    Args:
        Sport (_type_): _description_
    """

    name = "NAS"
    lineup_range = "J3:V61"


class TennisSport(Sport):
    """Tennis

    Args:
        Sport (_type_): _description_
    """

    name = "TEN"
    lineup_range = "J3:V61"
