"""Contract for `contest.metrics`. Loosely typed for now; a later change models it field by field."""

from __future__ import annotations

from dk_results.services.snapshot_v3.models.base import LooseSection


class ContestMetrics(LooseSection):
    """The `contest.metrics` section (derived contest metrics)."""
