"""Contract for a sport payload's `players` rows. Loosely typed for now; a later change models it field by field."""

from __future__ import annotations

from pydantic import model_validator

from dk_results.services.snapshot_v3.models.base import LooseSection
from dk_results.services.snapshot_v3.models.names import PADDED_NAME_MESSAGE, is_padded


class SportPlayer(LooseSection):
    """One row of a sport payload's `players`.

    Not typed field by field yet, but a `name` it carries has no leading or trailing whitespace.
    """

    @model_validator(mode="after")
    def _name_is_trimmed(self) -> SportPlayer:
        name = (self.model_extra or {}).get("name")
        if isinstance(name, str) and is_padded(name):
            raise ValueError(f"name {PADDED_NAME_MESSAGE}")
        return self
