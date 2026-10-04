"""Contract for `contest.train_clusters` rows. Loosely typed for now; a later change models it field by field."""

from __future__ import annotations

from dk_results.services.snapshot_v3.models.base import LooseSection


class TrainCluster(LooseSection):
    """One cluster of identical lineups in `contest.train_clusters`."""
