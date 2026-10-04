"""Contract for `contest.metrics`: derived contest metrics, each section omitted when unavailable."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, StrictBool, StrictInt, StrictStr, model_validator

from dk_results.services.snapshot_v3.models.base import ContractModel, omittable
from dk_results.services.snapshot_v3.models.names import TrimmedName
from dk_results.services.snapshot_v3.models.numbers import FiniteFloat, NonEmptyStr, NonNegativeFloat

TOP_REMAINING_PLAYERS_LIMIT = 10


class DistanceToCashVip(ContractModel):
    """How far one tracked VIP is from the cash line."""

    vip_entry_key: NonEmptyStr = omittable()
    entry_key: NonEmptyStr = omittable()
    display_name: NonEmptyStr = omittable()
    points_delta: FiniteFloat
    rank_delta: StrictInt = omittable()


class DistanceToCash(ContractModel):
    """Per-VIP distance to the cash line; present only when some VIP can be measured."""

    per_vip: list[DistanceToCashVip] = Field(min_length=1)
    cutoff_points: FiniteFloat = omittable()


class TopRemainingPlayer(ContractModel):
    """A player still to play on non-cashing lineups."""

    player_name: TrimmedName
    ownership_remaining_pct: FiniteFloat


class NonCashing(ContractModel):
    """The tally of users below the cash line.

    `top_remaining_players` is only emitted for sports that tally it (not MLB, not golf).
    """

    users_not_cashing: StrictInt = Field(ge=1)
    avg_pmr_remaining: FiniteFloat
    top_remaining_players: Annotated[list[TopRemainingPlayer], Field(max_length=TOP_REMAINING_PLAYERS_LIMIT)] = (
        omittable()
    )


class OwnershipSummaryVip(ContractModel):
    """Ownership totals for one tracked VIP lineup."""

    vip_entry_key: NonEmptyStr
    entry_key: NonEmptyStr = omittable()
    display_name: NonEmptyStr = omittable()
    total_ownership_pct: NonNegativeFloat
    ownership_in_play_pct: NonNegativeFloat = omittable()
    is_partial: StrictBool


class OwnershipSummary(ContractModel):
    """Ownership summary over the tracked VIP lineups."""

    source: Literal["vip_lineup_players"]
    scope: Literal["vip_lineup"]
    per_vip: list[OwnershipSummaryVip] = Field(min_length=1)


class SwingPlayer(ContractModel):
    """A player whose result can swing VIPs against the field."""

    player_key: NonEmptyStr
    player_name: TrimmedName
    vip_count: StrictInt = Field(ge=0)
    ownership_remaining_pct: FiniteFloat = omittable()


class VipVsFieldLeverage(ContractModel):
    """One VIP's remaining ownership against the contest field's."""

    vip_entry_key: NonEmptyStr
    entry_key: NonEmptyStr
    display_name: NonEmptyStr
    vip_remaining_pct: FiniteFloat
    field_remaining_pct: FiniteFloat
    uniqueness_delta_pct: FiniteFloat
    is_partial: StrictBool


_FIELD_REMAINING_KEYS = (
    "leverage_semantics",
    "field_remaining_scope",
    "field_remaining_source",
    "field_remaining_pct",
    "field_remaining_is_partial",
)


class Threat(ContractModel):
    """Threat metrics: swing players plus the field-remaining group (absent for sports with no Game status)."""

    top_swing_players: list[SwingPlayer] = omittable()
    leverage_semantics: Literal["positive=unique"] = omittable()
    field_remaining_scope: Literal["contest_field"] = omittable()
    field_remaining_source: Literal["contest_standings_mean"] = omittable()
    field_remaining_pct: FiniteFloat = omittable()
    field_remaining_is_partial: StrictBool = omittable()
    vip_vs_field_leverage: list[VipVsFieldLeverage] = omittable()

    @model_validator(mode="after")
    def _field_remaining_keys_travel_together(self) -> Threat:
        present = [key for key in _FIELD_REMAINING_KEYS if getattr(self, key) is not None]
        if present and len(present) != len(_FIELD_REMAINING_KEYS):
            missing = [key for key in _FIELD_REMAINING_KEYS if key not in present]
            raise ValueError(f"field-remaining keys appear together or not at all; missing {', '.join(missing)}")
        if self.vip_vs_field_leverage is not None and self.field_remaining_pct is None:
            raise ValueError("vip_vs_field_leverage requires field_remaining_pct")
        return self


class ContestMetrics(ContractModel):
    """The `contest.metrics` section (derived contest metrics)."""

    distance_to_cash: DistanceToCash = omittable()
    non_cashing: NonCashing = omittable()
    ownership_summary: OwnershipSummary = omittable()
    threat: Threat = omittable()
    updated_at: StrictStr
