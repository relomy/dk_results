"""Contract for `contest.live_metrics`."""

from __future__ import annotations

from typing import Literal

from pydantic import StrictInt, StrictStr, model_validator

from dk_results.services.snapshot_v3.models.base import ContractModel, omittable
from dk_results.services.snapshot_v3.models.numbers import FiniteFloat, NonNegativeFloat


class CashLine(ContractModel):
    """Where the cash line sits: a rank, a points total, or both."""

    cutoff_type: Literal["rank", "points", "unknown"]
    rank_cutoff: StrictInt = omittable()
    points_cutoff: FiniteFloat = omittable()

    @model_validator(mode="after")
    def _cutoff_matches_its_type(self) -> CashLine:
        if self.rank_cutoff is None and self.points_cutoff is None:
            raise ValueError("a cash line needs rank_cutoff or points_cutoff")
        if self.cutoff_type == "rank" and self.rank_cutoff is None:
            raise ValueError("cutoff_type rank requires rank_cutoff")
        if self.cutoff_type == "points" and self.points_cutoff is None:
            raise ValueError("cutoff_type points requires points_cutoff")
        return self


class LiveMetrics(ContractModel):
    """The `contest.live_metrics` section: figures that move while the contest is live."""

    cash_line: CashLine = omittable()
    avg_salary_per_player_remaining: NonNegativeFloat = omittable()
    updated_at: StrictStr
