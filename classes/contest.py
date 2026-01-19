"""Object representing a DraftKings contest from json."""

import datetime
import re
from dataclasses import dataclass, field


@dataclass
class Contest:
    """Object representing a DraftKings contest from json."""

    contest: dict = field(repr=False)
    sport: str
    start_date: str = field(init=False)
    name: str = field(init=False)
    id: int = field(init=False)
    draft_group: int = field(init=False)
    total_prizes: int = field(init=False)
    entries: int = field(init=False)
    entry_fee: int = field(init=False)
    entry_count: int = field(init=False)
    max_entry_count: int = field(init=False)
    attr: dict = field(init=False, repr=False)
    is_guaranteed: bool = field(init=False, default=False)
    is_double_up: bool = field(init=False, default=False)
    is_starred: bool = field(init=False, default=False)
    game_type: str = field(init=False)
    game_type_id: int = field(init=False)
    start_dt: datetime.datetime = field(init=False)

    def __post_init__(self):
        contest = self.contest
        self.start_date = contest["sd"]
        self.name = contest["n"].strip()
        self.id = contest["id"]
        self.draft_group = contest["dg"]
        self.total_prizes = contest["po"]
        self.entries = contest["m"]
        self.entry_fee = contest["a"]
        self.entry_count = contest["ec"]
        self.max_entry_count = contest["mec"]
        self.attr = contest["attr"]
        self.game_type = contest["gameType"]
        self.game_type_id = contest["gameTypeId"]

        self.start_dt = self.get_dt_from_timestamp(self.start_date)

        if "IsDoubleUp" in self.attr:
            self.is_double_up = self.attr["IsDoubleUp"]

        if "IsGuaranteed" in self.attr:
            self.is_guaranteed = self.attr["IsGuaranteed"]

        if "IsStarred" in self.attr:
            self.is_starred = self.attr["IsStarred"]

    @staticmethod
    def get_dt_from_timestamp(timestamp_str):
        """Convert timestamp to datetime object."""
        timestamp = float(re.findall(r"[^\d]*(\d+)[^\d]*", timestamp_str)[0])
        return datetime.datetime.fromtimestamp(timestamp / 1000)

    def __str__(self):
        return f"{vars(self)}"
