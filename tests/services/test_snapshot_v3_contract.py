"""The snapshot contract (pydantic models) checked through the envelope pipeline.

A fake collector returns a hand-built bundle; the real derive, builder, model
check and hand-written validator run, and assertions read the emitted envelope.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

from dk_results.services.snapshot_v3.models.envelope import contract_violations
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

    def test_hand_written_validator_still_runs_after_the_contract_passes(self) -> None:
        # Coherence between the sport key and the contest is not a shape the models express.
        with pytest.raises(ValueError, match="sports.nba.contests\\[0\\].sport must match sport key"):
            _build(_bundle(sport="nfl"))

    def test_null_the_contract_allows_is_emitted_and_passes(self) -> None:
        bundle = _bundle()
        assert "max_entries_per_user" not in bundle["contest"]

        contest = _build(bundle)["sports"]["nba"]["contests"][0]

        assert contest["max_entries_per_user"] is None


class TestContractViolations:
    def test_emitted_envelope_satisfies_the_contract(self) -> None:
        assert contract_violations(_build(_bundle())) == []

    @pytest.mark.parametrize("section", ["ownership_watchlist", "live_metrics", "metrics"])
    def test_null_on_an_omittable_section_is_rejected(self, section: str) -> None:
        envelope = _build(_bundle())
        envelope["sports"]["nba"]["contests"][0][section] = None

        assert contract_violations(envelope) == [f"sports.nba.contests[0].{section}: must be omitted, never null"]

    def test_numbers_are_not_coerced_from_strings(self) -> None:
        envelope = _build(_bundle())
        envelope["sports"]["nba"]["contests"][0]["entry_fee_cents"] = "1000"

        assert contract_violations(envelope) == [
            "sports.nba.contests[0].entry_fee_cents: Input should be a valid integer"
        ]

    def test_unknown_contest_key_is_rejected(self) -> None:
        envelope = _build(_bundle())
        envelope["sports"]["nba"]["contests"][0]["pts"] = 1.0

        assert contract_violations(envelope) == ["sports.nba.contests[0].pts: Extra inputs are not permitted"]

    def test_missing_required_field_is_named(self) -> None:
        envelope = _build(_bundle())
        del envelope["sports"]["nba"]["primary_contest"]["selected_at"]

        assert contract_violations(envelope) == ["sports.nba.primary_contest.selected_at: Field required"]
