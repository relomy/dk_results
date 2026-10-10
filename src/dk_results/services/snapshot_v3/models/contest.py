"""Contract for one contest in a sport payload's `contests`."""

from __future__ import annotations

from typing import Annotated

from pydantic import Field, StrictInt, StrictStr, model_validator

from dk_results.services.snapshot_v3.models.base import ContractModel, omittable
from dk_results.services.snapshot_v3.models.live_metrics import LiveMetrics
from dk_results.services.snapshot_v3.models.metrics import ContestMetrics
from dk_results.services.snapshot_v3.models.ownership_watchlist import OwnershipWatchlist
from dk_results.services.snapshot_v3.models.standings import StandingsRow
from dk_results.services.snapshot_v3.models.train_clusters import TrainCluster
from dk_results.services.snapshot_v3.models.vip_lineups import VipLineupRow


class Contest(ContractModel):
    """One DraftKings contest with its standings, VIP lineups and metrics."""

    contest_id: StrictStr
    contest_key: StrictStr
    name: StrictStr
    sport: StrictStr
    contest_type: StrictStr
    start_time: StrictStr
    state: StrictStr
    currency: StrictStr
    max_entries: StrictInt
    max_entries_per_user: StrictInt | None
    entry_fee_cents: StrictInt
    prize_pool_cents: StrictInt
    completed_at: StrictStr = omittable()
    positions_paid: Annotated[StrictInt, Field(ge=1)] = omittable()
    standings: list[StandingsRow]
    vip_lineups: list[VipLineupRow]
    train_clusters: list[TrainCluster]
    ownership_watchlist: OwnershipWatchlist = omittable()
    live_metrics: LiveMetrics = omittable()
    metrics: ContestMetrics = omittable()

    @model_validator(mode="after")
    def _non_cashing_fits_below_the_paid_positions(self) -> Contest:
        """Users below the cash line cannot outnumber the entries beyond the paid positions.

        The envelope carries no separate entry count, so `max_entries` (never below the real
        entry count) stands in for it, which can only loosen the bound. Skipped when
        `positions_paid` or the non-cashing metric is absent.
        """
        non_cashing = self.metrics.non_cashing if self.metrics else None
        if non_cashing is None or self.positions_paid is None:
            return self
        ceiling = max(self.max_entries - self.positions_paid, 0)
        if non_cashing.users_not_cashing > ceiling:
            raise ValueError(
                f"metrics.non_cashing.users_not_cashing ({non_cashing.users_not_cashing}) exceeds "
                f"max_entries ({self.max_entries}) minus positions_paid ({self.positions_paid})"
            )
        return self
