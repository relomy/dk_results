"""VIP ownership summary through the snapshot envelope pipeline.

A fake collector returns a hand-built bundle; the real builder and validator
run, and assertions read the emitted envelope the way the dashboard does.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

from dk_results.services.snapshot_v3.pipeline import build_snapshot_v3_envelope

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
    return {"player_name": name, "player_key": f"x:{name.lower()}", "salary": 5000, "is_live": True}


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
