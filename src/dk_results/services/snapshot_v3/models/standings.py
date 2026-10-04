"""Contract for `contest.standings` rows. Loosely typed for now; a later change models it field by field."""

from __future__ import annotations

from dk_results.services.snapshot_v3.models.base import LooseSection


class StandingsRow(LooseSection):
    """One row of `contest.standings`."""
