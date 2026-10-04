"""Contract for `contest.live_metrics`. Loosely typed for now; a later change models it field by field."""

from __future__ import annotations

from dk_results.services.snapshot_v3.models.base import LooseSection


class LiveMetrics(LooseSection):
    """The `contest.live_metrics` section."""
