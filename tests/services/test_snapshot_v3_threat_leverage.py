"""Field remaining and VIP-vs-field leverage through the snapshot envelope pipeline.

A fake collector returns a hand-built bundle; the real builder and validator
run, and assertions read the emitted ``metrics.threat`` the way the dashboard does.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

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


def _standing(entry_key: str, remaining: float | None, *, rank: int = 1) -> dict[str, Any]:
    return {
        "rank": rank,
        "entry_key": entry_key,
        "username": f"user-{entry_key}",
        "points": 100.0,
        "pmr": 10.0,
        "is_cashing": True,
        "ownership_remaining_total_pct": remaining,
        "is_vip": False,
    }


def _vip(entry_key: str, name: str) -> dict[str, Any]:
    return {"vip_entry_key": f"vip-{entry_key}", "entry_key": entry_key, "display_name": name}


def _bundle(sport: str = "NBA", **ownership: Any) -> dict[str, Any]:
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
        "cash_line": {},
    }


def _threat(bundle: dict[str, Any]) -> dict[str, Any]:
    envelope = build_snapshot_v3_envelope(
        {bundle["sport"]: 900},
        generated_at=GENERATED_AT,
        collector=lambda **_: deepcopy(bundle),
    )
    contest = envelope["sports"][bundle["sport"].lower()]["contests"][0]
    return contest.get("metrics", {}).get("threat", {})


def _field_bundle(sport: str = "NBA", *, field_pct: float = 41.236, partial: bool = False) -> dict[str, Any]:
    return _bundle(sport, field_remaining_pct=field_pct, field_remaining_is_partial=partial)


class TestFieldRemaining:
    def test_live_contest_with_zero_vips_emits_field_fields_and_no_leverage(self) -> None:
        bundle = _field_bundle()
        assert bundle["vip_lineups"] == []

        threat = _threat(bundle)

        assert threat == {
            "leverage_semantics": "positive=unique",
            "field_remaining_scope": "contest_field",
            "field_remaining_source": "contest_standings_mean",
            "field_remaining_pct": 41.24,
            "field_remaining_is_partial": False,
        }

    def test_sport_without_swing_players_still_emits_threat(self) -> None:
        bundle = _field_bundle("MLB")
        bundle["ownership"]["top_remaining_players"] = []
        bundle["ownership"]["non_cashing_top_remaining_players"] = []

        threat = _threat(bundle)

        assert threat["field_remaining_pct"] == 41.24
        assert "top_swing_players" not in threat

    def test_swing_players_and_field_remaining_share_one_threat(self) -> None:
        bundle = _field_bundle()
        bundle["ownership"]["top_remaining_players"] = [
            {"player_name": "A", "player_key": "x:a", "ownership_remaining_pct": 62.5}
        ]

        threat = _threat(bundle)

        assert [row["player_key"] for row in threat["top_swing_players"]] == ["x:a"]
        assert threat["field_remaining_pct"] == 41.24

    @pytest.mark.parametrize("partial", [True, False])
    def test_partial_flag_is_emitted_next_to_field_remaining(self, partial: bool) -> None:
        threat = _threat(_field_bundle(partial=partial))

        assert threat["field_remaining_is_partial"] is partial

    def test_omitted_for_golf_like_pool_without_game_status(self) -> None:
        bundle = _field_bundle("GOLF")
        bundle["players"] = [_player("A", "Masters Tournament"), _player("B", "Masters Tournament")]
        bundle["standings"] = [_standing("e1", 30.0)]
        bundle["vip_lineups"] = [_vip("e1", "Alice")]

        assert _threat(bundle) == {}

    def test_golf_keeps_swing_players_but_no_field_fields(self) -> None:
        bundle = _field_bundle("GOLF")
        bundle["players"] = [_player("A", "Masters Tournament")]
        bundle["ownership"]["top_remaining_players"] = [
            {"player_name": "A", "player_key": "x:a", "ownership_remaining_pct": 62.5}
        ]

        threat = _threat(bundle)

        assert set(threat) == {"top_swing_players"}

    def test_omitted_when_collector_could_not_compute_field_remaining(self) -> None:
        bundle = _bundle(field_remaining_pct=None, field_remaining_is_partial=True)
        bundle["standings"] = [_standing("e1", 30.0)]
        bundle["vip_lineups"] = [_vip("e1", "Alice")]

        assert _threat(bundle) == {}


class TestVipVsFieldLeverage:
    def test_row_per_matched_vip_with_signed_delta(self) -> None:
        bundle = _field_bundle(field_pct=40.0)
        bundle["standings"] = [_standing("e1", 25.5), _standing("e2", 55.0, rank=2)]
        bundle["vip_lineups"] = [_vip("e1", "Alice"), _vip("e2", "Bob")]

        rows = _threat(bundle)["vip_vs_field_leverage"]

        assert rows == [
            {
                "vip_entry_key": "vip-e1",
                "entry_key": "e1",
                "display_name": "Alice",
                "vip_remaining_pct": 25.5,
                "field_remaining_pct": 40.0,
                "uniqueness_delta_pct": 14.5,
            },
            {
                "vip_entry_key": "vip-e2",
                "entry_key": "e2",
                "display_name": "Bob",
                "vip_remaining_pct": 55.0,
                "field_remaining_pct": 40.0,
                "uniqueness_delta_pct": -15.0,
            },
        ]

    def test_vip_without_standings_row_is_absent(self) -> None:
        bundle = _field_bundle(field_pct=40.0)
        bundle["standings"] = [_standing("e1", 25.0)]
        bundle["vip_lineups"] = [_vip("e1", "Alice"), _vip("e9", "Ghost")]

        rows = _threat(bundle)["vip_vs_field_leverage"]

        assert [row["entry_key"] for row in rows] == ["e1"]

    def test_vip_whose_standings_row_has_no_remaining_is_absent(self) -> None:
        bundle = _field_bundle(field_pct=40.0)
        bundle["standings"] = [_standing("e1", None)]
        bundle["vip_lineups"] = [_vip("e1", "Alice")]

        assert "vip_vs_field_leverage" not in _threat(bundle)

    def test_no_matched_vip_omits_leverage_key(self) -> None:
        bundle = _field_bundle(field_pct=40.0)
        bundle["vip_lineups"] = [_vip("e9", "Ghost")]

        threat = _threat(bundle)

        assert "vip_vs_field_leverage" not in threat
        assert threat["field_remaining_pct"] == 40.0

    def test_entry_keys_match_across_int_and_string(self) -> None:
        bundle = _field_bundle(field_pct=40.0)
        bundle["standings"] = [_standing("77", 25.0)]
        bundle["standings"][0]["entry_key"] = 77
        bundle["vip_lineups"] = [_vip("77", "Alice")]

        assert len(_threat(bundle)["vip_vs_field_leverage"]) == 1

    def test_delta_uses_rounded_values_the_dashboard_sees(self) -> None:
        bundle = _field_bundle(field_pct=40.004)
        bundle["standings"] = [_standing("e1", 25.006)]
        bundle["vip_lineups"] = [_vip("e1", "Alice")]

        row = _threat(bundle)["vip_vs_field_leverage"][0]

        assert (row["vip_remaining_pct"], row["field_remaining_pct"], row["uniqueness_delta_pct"]) == (
            25.01,
            40.0,
            14.99,
        )

    def test_omitted_for_golf_like_pool_without_game_status(self) -> None:
        bundle = _field_bundle("GOLF", field_pct=40.0)
        bundle["players"] = [_player("A", "Masters Tournament")]
        bundle["standings"] = [_standing("e1", 25.0)]
        bundle["vip_lineups"] = [_vip("e1", "Alice")]

        assert "vip_vs_field_leverage" not in _threat(bundle)


class TestValidatorCoversNewFields:
    @pytest.mark.parametrize(
        ("mutation", "expected"),
        [
            ({"field_remaining_pct": "41"}, "threat.field_remaining_pct has invalid type"),
            ({"field_remaining_is_partial": "no"}, "threat.field_remaining_is_partial has invalid type"),
            ({"field_remaining_scope": "watchlist"}, "threat.field_remaining_scope has invalid value"),
            ({"field_remaining_source": "other"}, "threat.field_remaining_source has invalid value"),
            ({"leverage_semantics": "negative=unique"}, "threat.leverage_semantics has invalid value"),
        ],
    )
    def test_rejects_malformed_field_fields(self, mutation: dict[str, Any], expected: str) -> None:
        from dk_results.services.snapshot_v3.validate import validate_v3_envelope

        envelope = _envelope(_field_bundle())
        envelope["sports"]["nba"]["contests"][0]["metrics"]["threat"].update(mutation)

        violations = validate_v3_envelope(envelope)

        assert any(expected in v for v in violations), violations

    def test_rejects_field_remaining_without_partial_flag(self) -> None:
        from dk_results.services.snapshot_v3.validate import validate_v3_envelope

        envelope = _envelope(_field_bundle())
        del envelope["sports"]["nba"]["contests"][0]["metrics"]["threat"]["field_remaining_is_partial"]

        assert any("field_remaining_is_partial is required" in v for v in validate_v3_envelope(envelope))

    @pytest.mark.parametrize(
        ("field", "value", "expected"),
        [
            ("vip_entry_key", "", "vip_entry_key is required"),
            ("entry_key", None, "entry_key is required"),
            ("display_name", None, "display_name is required"),
            ("vip_remaining_pct", "x", "vip_remaining_pct has invalid type"),
            ("field_remaining_pct", None, "field_remaining_pct has invalid type"),
            ("uniqueness_delta_pct", float("nan"), "uniqueness_delta_pct has invalid type"),
        ],
    )
    def test_rejects_malformed_leverage_rows(self, field: str, value: Any, expected: str) -> None:
        from dk_results.services.snapshot_v3.validate import validate_v3_envelope

        bundle = _field_bundle(field_pct=40.0)
        bundle["standings"] = [_standing("e1", 25.0)]
        bundle["vip_lineups"] = [_vip("e1", "Alice")]
        envelope = _envelope(bundle)
        rows = envelope["sports"]["nba"]["contests"][0]["metrics"]["threat"]["vip_vs_field_leverage"]
        rows[0][field] = value

        violations = validate_v3_envelope(envelope)

        assert any(f"vip_vs_field_leverage[0].{expected}" in v for v in violations), violations

    def test_rejects_leverage_that_is_not_a_list(self) -> None:
        from dk_results.services.snapshot_v3.validate import validate_v3_envelope

        envelope = _envelope(_field_bundle())
        envelope["sports"]["nba"]["contests"][0]["metrics"]["threat"]["vip_vs_field_leverage"] = {}

        assert any("vip_vs_field_leverage has invalid type" in v for v in validate_v3_envelope(envelope))


def _envelope(bundle: dict[str, Any]) -> dict[str, Any]:
    return build_snapshot_v3_envelope(
        {bundle["sport"]: 900},
        generated_at=GENERATED_AT,
        collector=lambda **_: deepcopy(bundle),
    )
