"""Object representing a DraftKings contest from json.

``Contest`` is the parsed DraftKings *lobby row* — a read-only DTO validated
once at the DraftKings-payload boundary (see ADR-0003). Construct it only via
:meth:`Contest.from_lobby`, which validates the raw lobby ``dict`` field by
field and raises a naming :class:`pydantic.ValidationError` on drift.
"""

import datetime
import re
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ContestAttributes(BaseModel):
    """The nested DraftKings ``attr`` flags object.

    Each flag defaults to ``False`` when DraftKings omits it.
    """

    model_config = ConfigDict(frozen=True, populate_by_name=True, extra="ignore")

    is_double_up: bool = Field(default=False, alias="IsDoubleUp")
    is_guaranteed: bool = Field(default=False, alias="IsGuaranteed")
    is_starred: bool = Field(default=False, alias="IsStarred")


class Contest(BaseModel):
    """A validated, frozen DraftKings lobby contest.

    The terse DraftKings keys are mapped to readable field names via aliases;
    ``sport`` is supplied by the caller through :meth:`from_lobby`.
    """

    model_config = ConfigDict(frozen=True, populate_by_name=True, extra="ignore")

    id: int
    sport: str
    start_date: str = Field(alias="sd")
    name: str = Field(alias="n")
    draft_group: int = Field(alias="dg")
    total_prizes: int | float = Field(alias="po")
    entries: int = Field(alias="m")
    entry_fee: int | float = Field(alias="a")
    entry_count: int = Field(alias="ec")
    max_entry_count: int = Field(alias="mec")
    game_type: str = Field(alias="gameType")
    game_type_id: int = Field(alias="gameTypeId")
    attr: ContestAttributes

    @field_validator("name")
    @classmethod
    def _strip_name(cls, value: str) -> str:
        return value.strip()

    @classmethod
    def from_lobby(cls, dk_dict: Mapping[str, Any], sport: str) -> "Contest":
        """Validate a raw DraftKings lobby row into a ``Contest``.

        This is the only supported construction path. ``sport`` is merged in
        because the lobby row itself does not carry it.
        """
        return cls.model_validate({**dk_dict, "sport": sport})

    @property
    def is_double_up(self) -> bool:
        return self.attr.is_double_up

    @property
    def is_guaranteed(self) -> bool:
        return self.attr.is_guaranteed

    @property
    def is_starred(self) -> bool:
        return self.attr.is_starred

    @property
    def start_dt(self) -> datetime.datetime:
        """The contest start time parsed from the DraftKings ``/Date(...)/`` string."""
        return self.get_dt_from_timestamp(self.start_date)

    @staticmethod
    def get_dt_from_timestamp(timestamp_str: str) -> datetime.datetime:
        """Convert a DraftKings ``/Date(...)/`` timestamp to a datetime object."""
        timestamp = float(re.findall(r"[^\d]*(\d+)[^\d]*", timestamp_str)[0])
        return datetime.datetime.fromtimestamp(timestamp / 1000)
