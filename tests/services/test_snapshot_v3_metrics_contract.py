"""The contest metrics contract checked through the envelope pipeline.

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


def _player(name: str, status: str) -> dict[str, Any]:
    return {
        "name": name,
        "player_key": f"x:{name.lower()}",
        "position": "UTIL",
        "salary": 5000,
        "team": "AAA",
        "game_status": status,
        "ownership_pct": 10.0,
    }


def _bundle(sport: str = "NBA", *, cash_line: dict[str, Any] | None = None, **ownership: Any) -> dict[str, Any]:
    return {
        "sport": sport,
        "contest": {
            "contest_id": "900",
            "name": f"{sport} Contest",
            "sport": sport.lower(),
            "start_time_utc": "2026-10-04T00:00:00Z",
            "state": "live",
            "entry_fee": 10,
            "prize_pool": 1000,
            "max_entries": 100,
        },
        "selected_contest_id": "900",
        "selection_reason": {"mode": "explicit_id"},
        "players": [_player("A", "In Progress"), _player("B", "LAL@BOS 07:30PM ET")],
        "ownership": dict(ownership),
        "standings": [],
        "vip_lineups": [],
        "train_clusters": [],
        "cash_line": cash_line if cash_line is not None else {},
    }


def _build(bundle: dict[str, Any]) -> dict[str, Any]:
    return build_snapshot_v3_envelope(
        {bundle["sport"]: 900},
        generated_at=GENERATED_AT,
        collector=lambda **_: deepcopy(bundle),
    )


def _non_cashing_bundle(
    users_not_cashing: int, *, cash_line: dict[str, Any] | None, sport: str = "NBA"
) -> dict[str, Any]:
    return _bundle(
        sport,
        cash_line=cash_line,
        non_cashing_user_count=users_not_cashing,
        non_cashing_avg_pmr=120.0,
        non_cashing_top_remaining_players=[
            {"player_name": "A", "player_key": "x:a", "ownership_remaining_pct": 62.5},
        ],
    )


PAID_60 = {"cutoff_type": "positions_paid", "rank": 60, "points": 250.5}


class TestNonCashingCannotExceedEntriesMinusPositionsPaid:
    def test_count_above_the_bound_fails_the_build(self) -> None:
        # 100 entries, 60 paid: at most 40 can be non-cashing.
        with pytest.raises(ValueError, match="non_cashing.users_not_cashing"):
            _build(_non_cashing_bundle(41, cash_line=PAID_60))

    def test_count_at_the_bound_passes(self) -> None:
        envelope = _build(_non_cashing_bundle(40, cash_line=PAID_60))

        assert envelope["sports"]["nba"]["contests"][0]["metrics"]["non_cashing"]["users_not_cashing"] == 40

    def test_check_is_skipped_when_there_is_no_cash_line(self) -> None:
        envelope = _build(_non_cashing_bundle(500, cash_line=None))

        assert envelope["sports"]["nba"]["contests"][0]["metrics"]["non_cashing"]["users_not_cashing"] == 500

    def test_violation_names_the_non_cashing_path(self) -> None:
        envelope = _build(_non_cashing_bundle(40, cash_line=PAID_60))
        envelope["sports"]["nba"]["contests"][0]["metrics"]["non_cashing"]["users_not_cashing"] = 41

        assert len(contract_violations(envelope)) == 1
        assert contract_violations(envelope)[0].startswith("sports.nba.contests[0]: ")


def _rich_bundle(sport: str = "NBA") -> dict[str, Any]:
    bundle = _bundle(
        sport,
        cash_line=PAID_60,
        non_cashing_user_count=40,
        non_cashing_avg_pmr=120.0,
        non_cashing_top_remaining_players=[
            {"player_name": "A", "player_key": "x:a", "ownership_remaining_pct": 62.5},
        ],
        avg_salary_per_player_remaining=6000.0,
        field_remaining_pct=55.0,
        field_remaining_is_partial=False,
        vip_remaining_by_entry_key={"e1": 50.0},
    )
    bundle["vip_lineups"] = [
        {
            "vip_entry_key": "v1",
            "entry_key": "e1",
            "display_name": "VIP",
            "rank": 55,
            "points": 260.5,
            "players_live": [
                {"slot": "UTIL", "player_name": "A", "player_key": "x:a", "salary": 5000, "is_live": True}
            ],
        }
    ]
    return bundle


def _contest(envelope: dict[str, Any]) -> dict[str, Any]:
    return envelope["sports"]["nba"]["contests"][0]


class TestEmittedMetricsSatisfyTheContract:
    def test_every_metric_section_the_producer_emits_passes(self) -> None:
        envelope = _build(_rich_bundle())
        contest = _contest(envelope)

        assert set(contest["metrics"]) == {
            "distance_to_cash",
            "non_cashing",
            "ownership_summary",
            "threat",
            "updated_at",
        }
        assert set(contest["live_metrics"]) == {"cash_line", "avg_salary_per_player_remaining", "updated_at"}
        assert contract_violations(envelope) == []

    def test_sport_without_a_non_cashing_tally_has_no_top_remaining_players(self) -> None:
        envelope = _build(_non_cashing_bundle(40, cash_line=PAID_60, sport="MLB"))

        assert "top_remaining_players" not in _contest_for(envelope, "mlb")["metrics"]["non_cashing"]
        assert contract_violations(envelope) == []


def _contest_for(envelope: dict[str, Any], sport: str) -> dict[str, Any]:
    return envelope["sports"][sport]["contests"][0]


METRIC_PATH = "sports.nba.contests[0]"


def _violations_after(mutate: Any) -> list[str]:
    envelope = _build(_rich_bundle())
    mutate(_contest(envelope))
    return contract_violations(envelope)


class TestMetricsAreStrictlyTyped:
    def test_string_is_not_coerced_to_a_number(self) -> None:
        violations = _violations_after(lambda c: c["metrics"]["non_cashing"].update(avg_pmr_remaining="120.0"))

        assert violations == [f"{METRIC_PATH}.metrics.non_cashing.avg_pmr_remaining: Input should be a valid number"]

    def test_unknown_metric_key_is_rejected(self) -> None:
        violations = _violations_after(lambda c: c["metrics"]["threat"].update(mystery=1))

        assert violations == [f"{METRIC_PATH}.metrics.threat.mystery: Extra inputs are not permitted"]

    def test_null_on_an_omittable_metric_is_rejected(self) -> None:
        violations = _violations_after(lambda c: c["metrics"]["non_cashing"].update(top_remaining_players=None))

        assert violations == [f"{METRIC_PATH}.metrics.non_cashing.top_remaining_players: must be omitted, never null"]

    def test_null_cash_line_cutoff_is_rejected(self) -> None:
        violations = _violations_after(lambda c: c["live_metrics"]["cash_line"].update(points_cutoff=None))

        assert violations == [f"{METRIC_PATH}.live_metrics.cash_line.points_cutoff: must be omitted, never null"]

    def test_non_cashing_requires_its_count(self) -> None:
        violations = _violations_after(lambda c: c["metrics"]["non_cashing"].pop("users_not_cashing"))

        assert violations == [f"{METRIC_PATH}.metrics.non_cashing.users_not_cashing: Field required"]

    def test_more_than_ten_top_remaining_players_is_rejected(self) -> None:
        rows = [{"player_name": f"P{i}", "ownership_remaining_pct": 1.0} for i in range(11)]

        violations = _violations_after(lambda c: c["metrics"]["non_cashing"].update(top_remaining_players=rows))

        assert len(violations) == 1
        assert violations[0].startswith(f"{METRIC_PATH}.metrics.non_cashing.top_remaining_players: ")

    def test_threat_field_remaining_keys_travel_together(self) -> None:
        violations = _violations_after(lambda c: c["metrics"]["threat"].pop("field_remaining_is_partial"))

        assert len(violations) == 1
        assert "field_remaining_is_partial" in violations[0]

    def test_threat_enum_value_is_pinned(self) -> None:
        violations = _violations_after(lambda c: c["metrics"]["threat"].update(leverage_semantics="negative=unique"))

        assert len(violations) == 1
        assert violations[0].startswith(f"{METRIC_PATH}.metrics.threat.leverage_semantics: ")

    def test_ownership_summary_percentages_cannot_be_negative(self) -> None:
        def mutate(contest: dict[str, Any]) -> None:
            contest["metrics"]["ownership_summary"]["per_vip"][0]["total_ownership_pct"] = -1.0

        violations = _violations_after(mutate)

        assert len(violations) == 1
        assert violations[0].startswith(f"{METRIC_PATH}.metrics.ownership_summary.per_vip[0].total_ownership_pct: ")

    def test_distance_to_cash_row_needs_points_delta(self) -> None:
        violations = _violations_after(lambda c: c["metrics"]["distance_to_cash"]["per_vip"][0].pop("points_delta"))

        assert violations == [f"{METRIC_PATH}.metrics.distance_to_cash.per_vip[0].points_delta: Field required"]

    def test_negative_average_salary_is_rejected(self) -> None:
        violations = _violations_after(lambda c: c["live_metrics"].update(avg_salary_per_player_remaining=-1.0))

        assert len(violations) == 1
        assert violations[0].startswith(f"{METRIC_PATH}.live_metrics.avg_salary_per_player_remaining: ")

    def test_cash_line_of_rank_type_needs_a_rank_cutoff(self) -> None:
        def mutate(contest: dict[str, Any]) -> None:
            contest["live_metrics"]["cash_line"].pop("rank_cutoff")

        violations = _violations_after(mutate)

        assert len(violations) == 1
        assert violations[0].startswith(f"{METRIC_PATH}.live_metrics.cash_line: ")


class TestProducerOmitsWhatItCannotKnow:
    def test_cash_line_with_only_a_rank_omits_the_points_cutoff(self) -> None:
        envelope = _build(_bundle(cash_line={"cutoff_type": "positions_paid", "rank": 60, "points": None}))

        assert _contest(envelope)["live_metrics"]["cash_line"] == {"cutoff_type": "rank", "rank_cutoff": 60}
        assert contract_violations(envelope) == []

    def test_cash_line_with_only_points_omits_the_rank_cutoff(self) -> None:
        envelope = _build(_bundle(cash_line={"cutoff_type": "points", "rank": None, "points": 250.5}))

        assert _contest(envelope)["live_metrics"]["cash_line"] == {"cutoff_type": "points", "points_cutoff": 250.5}
        assert contract_violations(envelope) == []

    def test_distance_to_cash_row_omits_identity_a_vip_lacks(self) -> None:
        bundle = _bundle(cash_line=PAID_60)
        bundle["vip_lineups"] = [{"vip_entry_key": "v1", "rank": 55, "points": 260.5}]

        envelope = _build(bundle)

        assert _contest(envelope)["metrics"]["distance_to_cash"]["per_vip"] == [
            {"vip_entry_key": "v1", "points_delta": 10.0, "rank_delta": 5}
        ]
        assert contract_violations(envelope) == []
