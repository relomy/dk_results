"""VIP ownership summary through the snapshot envelope pipeline.

A fake collector returns a hand-built bundle; the real builder and validator
run, and assertions read the emitted envelope the way the dashboard does.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

from dk_results.services.snapshot_v3.derive import derive_ownership_summary
from dk_results.services.snapshot_v3.pipeline import build_snapshot_v3_envelope
from dk_results.services.snapshot_v3.validate import validate_v3_envelope

GENERATED_AT = "2026-10-04T12:00:00Z"


def _player(name: str, status: str, ownership_pct: float) -> dict[str, Any]:
    return {
        "name": name,
        "player_key": f"x:{name.lower()}",
        "position": "UTIL",
        "salary": 5000,
        "team": "AAA",
        "game_status": status,
        "ownership_pct": ownership_pct,
    }


def _slot(name: str) -> dict[str, Any]:
    return {
        "slot": "UTIL",
        "player_name": name,
        "player_key": f"x:{name.lower()}",
        "salary": 5000,
        "is_live": True,
    }


def _vip(vip_entry_key: str, *slots: dict[str, Any]) -> dict[str, Any]:
    return {
        "vip_entry_key": vip_entry_key,
        "entry_key": f"e-{vip_entry_key}",
        "display_name": f"vip {vip_entry_key}",
        "players_live": list(slots),
    }


def _bundle(players: list[dict[str, Any]], vips: list[dict[str, Any]], sport: str = "NBA") -> dict[str, Any]:
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
        "players": players,
        "ownership": {},
        "standings": [],
        "vip_lineups": vips,
        "train_clusters": [],
        "cash_line": {},
    }


def _contest(bundle: dict[str, Any]) -> dict[str, Any]:
    envelope = build_snapshot_v3_envelope(
        {bundle["sport"]: 900},
        generated_at=GENERATED_AT,
        collector=lambda **_: deepcopy(bundle),
    )
    return envelope["sports"][bundle["sport"].lower()]["contests"][0]


def _per_vip(bundle: dict[str, Any]) -> list[dict[str, Any]]:
    summary = _contest(bundle)["metrics"]["ownership_summary"]
    assert summary["source"] == "vip_lineup_players"
    assert summary["scope"] == "vip_lineup"
    return summary["per_vip"]


class TestOwnershipInPlay:
    def test_sums_every_slot_and_only_in_play_slots(self) -> None:
        players = [
            _player("Pre", "LAL@BOS 07:30PM ET", 10.0),
            _player("Live", "In Progress", 20.0),
            _player("Done", "Final", 40.0),
        ]
        bundle = _bundle(players, [_vip("v1", _slot("Pre"), _slot("Live"), _slot("Done"))])

        assert _per_vip(bundle) == [
            {
                "vip_entry_key": "v1",
                "entry_key": "e-v1",
                "display_name": "vip v1",
                "total_ownership_pct": 70.0,
                "ownership_in_play_pct": 20.0,
                "is_partial": False,
            }
        ]

    @pytest.mark.parametrize(
        ("status", "counted"),
        [
            ("In-Progress", True),
            ("Delayed", True),
            ("Suspended", True),
            ("LAL@BOS 07:30PM ET", False),
            ("Final", False),
            ("Postponed", False),
            ("Cancelled", False),
            ("Canceled", False),
        ],
    )
    def test_game_status_decides_in_play(self, status: str, counted: bool) -> None:
        players = [_player("A", status, 12.5), _player("Anchor", "In Progress", 1.0)]
        bundle = _bundle(players, [_vip("v1", _slot("A"))])

        row = _per_vip(bundle)[0]

        assert row["total_ownership_pct"] == 12.5
        assert row["ownership_in_play_pct"] == (12.5 if counted else 0.0)
        assert row["is_partial"] is False

    def test_rounds_sums_to_two_decimals(self) -> None:
        players = [_player("A", "In Progress", 10.123), _player("B", "In Progress", 20.456)]
        bundle = _bundle(players, [_vip("v1", _slot("A"), _slot("B"))])

        row = _per_vip(bundle)[0]

        assert row["total_ownership_pct"] == 30.58
        assert row["ownership_in_play_pct"] == 30.58

    def test_one_row_per_vip_in_vip_key_order(self) -> None:
        players = [_player("A", "In Progress", 10.0), _player("B", "Final", 30.0)]
        bundle = _bundle(players, [_vip("v2", _slot("B")), _vip("v1", _slot("A"))])

        rows = _per_vip(bundle)

        assert [(r["vip_entry_key"], r["total_ownership_pct"]) for r in rows] == [("v1", 10.0), ("v2", 30.0)]


class TestPartialSummary:
    def test_unmatched_player_key_is_partial_and_adds_nothing(self) -> None:
        players = [_player("A", "In Progress", 10.0)]
        bundle = _bundle(players, [_vip("v1", _slot("A"), _slot("Ghost"))])

        row = _per_vip(bundle)[0]

        assert row["is_partial"] is True
        assert row["total_ownership_pct"] == 10.0
        assert row["ownership_in_play_pct"] == 10.0

    def test_locked_slot_is_partial(self) -> None:
        players = [_player("A", "In Progress", 10.0)]
        locked = {"slot": "UTIL", "player_name": "LOCKED 🔒", "is_locked": True}
        bundle = _bundle(players, [_vip("v1", _slot("A"), locked)])

        row = _per_vip(bundle)[0]

        assert row["is_partial"] is True
        assert row["total_ownership_pct"] == 10.0

    def test_locked_slot_is_partial_even_when_key_matches_a_player(self) -> None:
        players = [_player("A", "In Progress", 10.0)]
        locked = {"slot": "UTIL", "player_name": "LOCKED 🔒", "is_locked": True}
        bundle = _bundle(players, [_vip("v1", locked)])

        assert _per_vip(bundle)[0]["is_partial"] is True

    def test_explicit_locked_flag_wins_over_display_name_and_adds_nothing(self) -> None:
        players = [_player("A", "In Progress", 10.0)]
        locked = {
            "slot": "UTIL",
            "player_name": "unrevealed",
            "player_key": "x:a",
            "is_locked": True,
        }
        bundle = _bundle(players, [_vip("v1", locked)])

        row = derive_ownership_summary(bundle)["per_vip"][0]

        assert row["is_partial"] is True
        assert row["total_ownership_pct"] == 0.0
        assert row["ownership_in_play_pct"] == 0.0

    def test_unknown_status_is_partial_but_counts_toward_total(self) -> None:
        players = [_player("A", "In Progress", 10.0), _player("Odd", "Weather Hold", 5.0)]
        bundle = _bundle(players, [_vip("v1", _slot("A"), _slot("Odd"))])

        row = _per_vip(bundle)[0]

        assert row["is_partial"] is True
        assert row["total_ownership_pct"] == 15.0
        assert row["ownership_in_play_pct"] == 10.0

    def test_partial_flag_is_per_vip(self) -> None:
        players = [_player("A", "In Progress", 10.0)]
        bundle = _bundle(players, [_vip("v1", _slot("A")), _vip("v2", _slot("A"), _slot("Ghost"))])

        assert [r["is_partial"] for r in _per_vip(bundle)] == [False, True]


class TestOmission:
    def test_identity_fields_missing_from_the_vip_row_are_omitted_not_null(self) -> None:
        vip = _vip("v1", _slot("A"))
        del vip["display_name"], vip["entry_key"]
        bundle = _bundle([_player("A", "In Progress", 10.0)], [vip])

        assert set(_per_vip(bundle)[0]) == {
            "vip_entry_key",
            "total_ownership_pct",
            "ownership_in_play_pct",
            "is_partial",
        }

    def test_vip_without_lineup_slots_is_left_out(self) -> None:
        bundle = _bundle([_player("A", "In Progress", 10.0)], [_vip("v1")])

        assert "ownership_summary" not in _contest(bundle).get("metrics", {})

    def test_absent_with_zero_tracked_vips(self) -> None:
        bundle = _bundle([_player("A", "In Progress", 10.0)], [])

        assert "ownership_summary" not in _contest(bundle).get("metrics", {})

    def test_golf_like_pool_omits_in_play_but_keeps_totals(self) -> None:
        players = [_player("A", "Masters Tournament", 10.0), _player("B", "Masters Tournament", 15.0)]
        bundle = _bundle(players, [_vip("v1", _slot("A"), _slot("B"))], sport="GOLF")

        row = _per_vip(bundle)[0]

        assert row["total_ownership_pct"] == 25.0
        assert "ownership_in_play_pct" not in row
        assert row["is_partial"] is True

    def test_does_not_restore_pre_v3_in_play_source(self) -> None:
        bundle = _bundle([_player("A", "In Progress", 10.0)], [_vip("v1", _slot("A"))])

        summary = _contest(bundle)["metrics"]["ownership_summary"]

        assert "ownership_in_play_source" not in summary
        assert "ownership_in_play_source" not in summary["per_vip"][0]


class TestValidator:
    def _envelope(self) -> dict[str, Any]:
        bundle = _bundle([_player("A", "In Progress", 10.0)], [_vip("v1", _slot("A"))])
        return build_snapshot_v3_envelope(
            {"NBA": 900}, generated_at=GENERATED_AT, collector=lambda **_: deepcopy(bundle)
        )

    def _violations(self, mutate: Any) -> list[str]:
        envelope = self._envelope()
        assert validate_v3_envelope(envelope) == []
        summary = envelope["sports"]["nba"]["contests"][0]["metrics"]["ownership_summary"]
        mutate(summary)
        return validate_v3_envelope(envelope)

    @pytest.mark.parametrize(
        ("mutate", "expected"),
        [
            (lambda s: s.update(source="other"), "ownership_summary.source must be vip_lineup_players"),
            (lambda s: s.update(scope="watchlist"), "ownership_summary.scope must be vip_lineup"),
            (lambda s: s.update(per_vip={}), "ownership_summary.per_vip has invalid type"),
            (lambda s: s.pop("per_vip"), "ownership_summary.per_vip has invalid type"),
            (lambda s: s["per_vip"].append("x"), "per_vip[1] must be an object"),
            (lambda s: s["per_vip"][0].pop("vip_entry_key"), "per_vip[0].vip_entry_key is required"),
            (lambda s: s["per_vip"][0].update(entry_key=7), "per_vip[0].entry_key has invalid type"),
            (lambda s: s["per_vip"][0].update(display_name=7), "per_vip[0].display_name has invalid type"),
            (lambda s: s["per_vip"][0].pop("total_ownership_pct"), "per_vip[0].total_ownership_pct is required"),
            (lambda s: s["per_vip"][0].update(total_ownership_pct="9"), "per_vip[0].total_ownership_pct has invalid"),
            (lambda s: s["per_vip"][0].update(total_ownership_pct=-1.0), "per_vip[0].total_ownership_pct has invalid"),
            (lambda s: s["per_vip"][0].update(ownership_in_play_pct=None), "per_vip[0].ownership_in_play_pct has"),
            (lambda s: s["per_vip"][0].update(ownership_in_play_pct=float("nan")), "ownership_in_play_pct has"),
            (lambda s: s["per_vip"][0].pop("is_partial"), "per_vip[0].is_partial is required"),
            (lambda s: s["per_vip"][0].update(is_partial=1), "per_vip[0].is_partial has invalid type"),
        ],
    )
    def test_rejects_malformed_summary(self, mutate: Any, expected: str) -> None:
        violations = self._violations(mutate)

        assert any(expected in v and "metrics.ownership_summary" in v for v in violations), violations

    def test_allows_missing_in_play_for_golf_like_rows(self) -> None:
        assert self._violations(lambda s: s["per_vip"][0].pop("ownership_in_play_pct")) == []
