"""Object representing a DraftKings contest from json."""

import datetime
import re


class Contest:
    """Object representing a DraftKings contest from json."""

    def __init__(self, contest, sport):
        self.sport = sport
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
        self.is_guaranteed = False
        self.is_double_up = False

        self.start_dt = self.get_dt_from_timestamp(self.start_date)

        if "IsDoubleUp" in self.attr:
            self.is_double_up = self.attr["IsDoubleUp"]

        if "IsGuaranteed" in self.attr:
            self.is_guaranteed = self.attr["IsGuaranteed"]

    @staticmethod
    def get_dt_from_timestamp(timestamp_str):
        """Convert timestamp to datetime object."""
        timestamp = float(re.findall(r"[^\d]*(\d+)[^\d]*", timestamp_str)[0])
        return datetime.datetime.fromtimestamp(timestamp / 1000)

    def __str__(self):
        return f"{vars(self)}"
