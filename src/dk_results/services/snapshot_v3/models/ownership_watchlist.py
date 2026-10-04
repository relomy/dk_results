"""Contract for `contest.ownership_watchlist`. Loosely typed for now; a later change models it field by field."""

from __future__ import annotations

from dk_results.services.snapshot_v3.models.base import LooseSection


class OwnershipWatchlist(LooseSection):
    """The `contest.ownership_watchlist` section."""
