"""Contract for a sport payload's `players` rows. Loosely typed for now; a later change models it field by field."""

from __future__ import annotations

from dk_results.services.snapshot_v3.models.base import LooseSection


class SportPlayer(LooseSection):
    """One row of a sport payload's `players`."""
