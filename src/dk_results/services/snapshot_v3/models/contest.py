"""Contract for one contest in a sport payload's `contests`."""

from __future__ import annotations

from pydantic import StrictInt, StrictStr

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
    standings: list[StandingsRow]
    vip_lineups: list[VipLineupRow]
    train_clusters: list[TrainCluster]
    ownership_watchlist: OwnershipWatchlist = omittable()
    live_metrics: LiveMetrics = omittable()
    metrics: ContestMetrics = omittable()
