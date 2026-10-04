"""Contract for `contest.vip_lineups` rows. Loosely typed for now; a later change models it field by field."""

from __future__ import annotations

from dk_results.services.snapshot_v3.models.base import LooseSection


class VipLineupRow(LooseSection):
    """One tracked VIP's lineup in `contest.vip_lineups`."""
