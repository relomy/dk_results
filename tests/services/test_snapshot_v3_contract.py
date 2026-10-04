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

    def test_a_fault_both_checks_catch_is_reported_once(self) -> None:
        bundle = _bundle()
        bundle["vip_lineups"] = [{"entry_key": "e1", "players_live": [{"slot": "PG", "is_live": True}]}]

        message = _build_error(bundle)

        assert message.count("players_live[0].player_name") == 1

    def test_hand_written_validator_is_skipped_while_the_models_fail(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[Any] = []
        monkeypatch.setattr(
            "dk_results.services.snapshot_v3.pipeline.validate_v3_envelope",
            lambda envelope: calls.append(envelope) or [],
        )

        with pytest.raises(ValueError):
            _build(_bundle(max_entries="100"))

        assert calls == []

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


def _vip_bundle(*, slots: list[dict[str, Any]] | None = None, **row: Any) -> dict[str, Any]:
    bundle = _bundle()
    bundle["vip_lineups"] = [
        {
            "display_name": "vipuser",
            "entry_key": "e1",
            "vip_entry_key": "e1",
            "rank": 55,
            "points": 260.75,
            "pmr": 120.0,
            "players_live": slots
            if slots is not None
            else [
                {"slot": "PG", "player_name": "Player A", "player_key": "nba:a", "salary": 8000, "is_live": True},
                {"slot": "SG", "player_name": "LOCKED 🔒", "is_locked": True},
            ],
            **row,
        }
    ]
    return bundle


def _build_error(bundle: dict[str, Any]) -> str:
    with pytest.raises(ValueError) as excinfo:
        _build(bundle)
    return str(excinfo.value)


class TestVipLineupsContract:
    def test_properly_typed_rows_and_slots_build(self) -> None:
        vip = _build(_vip_bundle())["sports"]["nba"]["contests"][0]["vip_lineups"][0]

        assert (vip["rank"], vip["points"], vip["pmr"]) == (55, 260.75, 120.0)

    def test_figures_and_slots_may_be_omitted(self) -> None:
        bundle = _bundle()
        bundle["vip_lineups"] = [{"entry_key": "e1"}]

        assert _build(bundle)["sports"]["nba"]["contests"][0]["vip_lineups"] == [{"entry_key": "e1"}]

    @pytest.mark.parametrize("field", ["rank", "pmr", "points"])
    def test_string_figure_fails_the_build(self, field: str) -> None:
        message = _build_error(_vip_bundle(**{field: "55"}))

        assert f"sports.nba.contests[0].vip_lineups[0].{field}: Input should be a valid" in message

    def test_points_under_the_wrong_field_name_fail_the_build(self) -> None:
        bundle = _vip_bundle()
        del bundle["vip_lineups"][0]["points"]
        bundle["vip_lineups"][0]["pts"] = 260.75

        assert "sports.nba.contests[0].vip_lineups[0].pts: Extra inputs are not permitted" in _build_error(bundle)

    def test_null_figure_fails_the_build(self) -> None:
        message = _build_error(_vip_bundle(rank=None))

        assert "sports.nba.contests[0].vip_lineups[0].rank: must be omitted, never null" in message

    def test_slot_with_wrongly_typed_salary_fails_the_build(self) -> None:
        slot = {"slot": "PG", "player_name": "Player A", "salary": "8000", "is_live": True}

        message = _build_error(_vip_bundle(slots=[slot]))

        assert (
            "sports.nba.contests[0].vip_lineups[0].players_live[0].salary: Input should be a valid integer" in message
        )

    def test_slot_without_a_player_name_fails_the_build(self) -> None:
        message = _build_error(_vip_bundle(slots=[{"slot": "PG", "is_live": True}]))

        assert "sports.nba.contests[0].vip_lineups[0].players_live[0].player_name: Field required" in message

    @pytest.mark.parametrize("name", [" Player A", "Player A ", "Player A\n"])
    def test_padded_player_name_fails_the_build(self, name: str) -> None:
        message = _build_error(_vip_bundle(slots=[{"slot": "PG", "player_name": name, "is_live": True}]))

        assert "players_live[0].player_name: must not have leading or trailing whitespace" in message

    @pytest.mark.parametrize(
        ("field", "value"), [("player_key", "nba:a"), ("salary", 8000), ("is_live", True), ("is_live", False)]
    )
    def test_locked_slot_carrying_player_state_fails_the_build(self, field: str, value: Any) -> None:
        slot = {"slot": "PG", "player_name": "LOCKED 🔒", "is_locked": True, field: value}

        message = _build_error(_vip_bundle(slots=[slot]))

        assert f"players_live[0].{field} is forbidden for locked slot" in message

    def test_locked_sentinel_without_the_locked_flag_fails_the_build(self) -> None:
        message = _build_error(_vip_bundle(slots=[{"slot": "PG", "player_name": "LOCKED 🔒", "is_live": False}]))

        assert "players_live[0].is_locked must be true for locked slot" in message
