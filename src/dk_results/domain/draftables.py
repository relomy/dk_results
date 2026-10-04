"""DraftKings draftables payload for one draft group.

``Draftables`` is a read-only DTO validated once at the DraftKings-payload
boundary (see ADR-0003). Construct it only via :meth:`Draftables.from_payload`,
which raises a naming :class:`pydantic.ValidationError` on drift. It parses only
what a player's Matchup needs and ignores every other field. Its output,
:meth:`Draftables.matchups_by_draftable_id`, is a plain ``dict`` so pydantic
types stay inside this adapter.
"""

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

_CONFIG = ConfigDict(frozen=True, populate_by_name=True, extra="ignore")


class _Team(BaseModel):
    model_config = _CONFIG

    abbreviation: str


class _Competition(BaseModel):
    """One Competition (real-world game or event) in the draft group."""

    model_config = _CONFIG

    competition_id: int = Field(alias="competitionId")
    home_team: _Team = Field(alias="homeTeam")
    away_team: _Team = Field(alias="awayTeam")
    competition_state: str = Field(alias="competitionState")

    def matchup_for(self, team: str) -> str | None:
        """The Matchup for a player on ``team``, or ``None`` when there is no opponent."""
        home = self.home_team.abbreviation
        away = self.away_team.abbreviation
        if home == away:
            return None
        if team == home:
            return f"vs. {away}"
        if team == away:
            return f"at {home}"
        return None


class _CompetitionRef(BaseModel):
    model_config = _CONFIG

    competition_id: int = Field(alias="competitionId")


class _Draftable(BaseModel):
    """One player in one roster slot."""

    model_config = _CONFIG

    draftable_id: int = Field(alias="draftableId")
    team_abbreviation: str = Field(alias="teamAbbreviation")
    competition: _CompetitionRef


class Draftables(BaseModel):
    """A validated, frozen DraftKings draftables payload."""

    model_config = _CONFIG

    draftables: list[_Draftable]
    competitions: list[_Competition]

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "Draftables":
        """Validate a raw draftables payload. This is the only supported construction path."""
        return cls.model_validate(payload)

    def matchups_by_draftable_id(self) -> dict[str, str | None]:
        """Map each draftable ID (as a string, like the salary CSV ``ID``) to its Matchup.

        A draftable maps to ``None`` when its Competition has no opponent for it.
        """
        competitions = {competition.competition_id: competition for competition in self.competitions}
        matchups: dict[str, str | None] = {}
        for draftable in self.draftables:
            competition = competitions.get(draftable.competition.competition_id)
            matchup = competition.matchup_for(draftable.team_abbreviation) if competition else None
            matchups[str(draftable.draftable_id)] = matchup
        return matchups
