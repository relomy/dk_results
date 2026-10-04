"""The snapshot contract (pydantic models) checked through the envelope pipeline.

A fake collector returns a hand-built bundle; the real derive, builder, model
check and hand-written validator run, and assertions read the emitted envelope.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

from dk_results.services.snapshot_v3.pipeline import build_snapshot_v3_envelope

GENERATED_AT = "2026-10-04T12:00:00Z"


def _bundle(**contest: Any) -> dict[str, Any]:
    return {
        "sport": "NBA",
        "contest": {
            "contest_id": "900",
            "name": "NBA Contest",
            "sport": "nba",
            "start_time_utc": "2026-10-04T00:00:00Z",
            "state": "live",
            "entry_fee": 10,
            "prize_pool": 1000,
            "max_entries": 100,
            **contest,
        },
        "selected_contest_id": "900",
        "selection_reason": {"mode": "explicit_id"},
        "players": [],
        "ownership": {},
        "standings": [],
        "vip_lineups": [],
        "train_clusters": [],
        "cash_line": {},
    }


def _build(bundle: dict[str, Any]) -> dict[str, Any]:
    return build_snapshot_v3_envelope(
        {bundle["sport"]: 900},
        generated_at=GENERATED_AT,
        collector=lambda **_: deepcopy(bundle),
    )


class TestPipelineEnforcesContract:
    def test_wrongly_typed_field_fails_the_build_with_its_contract_path(self) -> None:
        with pytest.raises(ValueError) as excinfo:
            _build(_bundle(max_entries="100"))

        message = str(excinfo.value)
        assert message.startswith("Snapshot v3 validation failed: ")
        assert "sports.nba.contests[0].max_entries: Input should be a valid integer" in message
