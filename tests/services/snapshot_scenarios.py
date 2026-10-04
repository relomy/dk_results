"""Scenario bundles behind the golden envelopes (see ``test_snapshot_v3_goldens.py``).

Add a scenario with one bundle builder and one ``SCENARIOS`` entry; its golden is
written by the regenerate command documented in ``docs/TESTING.md``.
"""

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from dk_results.services.snapshot_v3.pipeline import build_snapshot_v3_envelope

GENERATED_AT = "2026-10-04T12:00:00Z"


@dataclass(frozen=True)
class Scenario:
    """A golden: ``name`` is the file stem under ``contract/goldens/``."""

    name: str
    sport: str
    contest_id: int
    bundle: Callable[[], dict[str, Any]]


def build_envelope(scenario: Scenario) -> dict[str, Any]:
    """Run the real pipeline over the scenario's bundle with an injected collector."""
    return build_snapshot_v3_envelope(
        {scenario.sport: scenario.contest_id},
        generated_at=GENERATED_AT,
        collector=lambda **_: deepcopy(scenario.bundle()),
    )


def _slot(slot: str, name: str, key: str, salary: int, *, live: bool = True) -> dict[str, Any]:
    return {"slot": slot, "player_name": name, "player_key": key, "salary": salary, "is_live": live}


def _standing(rank: int, entry: str, user: str, points: float, pmr: float, **extra: Any) -> dict[str, Any]:
    return {
        "rank": rank,
        "entry_key": entry,
        "username": user,
        "pmr": pmr,
        "points": points,
        "payout_cents": None,
        "is_cashing": False,
        "ownership_remaining_total_pct": None,
        "remaining_salary": 0,
        "is_vip": False,
        **extra,
    }


def _golf_bundle() -> dict[str, Any]:
    """Golf: every player's status is the tournament name, so the sport has no Game status."""
    tournament = "Masters Tournament"
    field = [
        ("Scottie Scheffler", 12000, 31.5),
        ("Rory McIlroy", 11000, 22.0),
        ("Jon Rahm", 10500, 18.5),
        ("Xander Schauffele", 9800, 14.0),
        ("Viktor Hovland", 9200, 11.5),
        ("Collin Morikawa", 8800, 9.0),
        ("Tommy Fleetwood", 8200, 7.5),
        ("Sahith Theegala", 7600, 5.0),
    ]
    players = [
        {
            "name": name,
            "player_key": f"golf:{name.lower().replace(' ', '-')}",
            "position": "G",
            "roster_positions": ["G"],
            "salary": salary,
            "team": "",
            "game_status": tournament,
            "ownership_pct": own,
            "fantasy_points": 0.0,
            "value": 0.0,
        }
        for name, salary, own in field
    ]
    slots = [_slot("G", p["name"], p["player_key"], p["salary"], live=False) for p in players[:6]]
    return {
        "sport": "GOLF",
        "contest": {
            "contest_id": "300100",
            "name": "PGA $20 Double Up",
            "sport": "golf",
            "contest_type": "classic",
            "start_time_utc": "2026-04-09T12:00:00Z",
            "state": "live",
            "entry_fee": 20,
            "prize_pool": 8000,
            "currency": "USD",
            "max_entries": 100,
            "max_entries_per_user": 1,
        },
        "selected_contest_id": "300100",
        "selection_reason": {"mode": "explicit_id", "criteria": {"contest_id": "300100"}},
        "players": players,
        "standings": [
            _standing(1, "g1", "birdie_hunter", 412.5, 0.0, payout_cents=4000, is_cashing=True),
            _standing(2, "g2", "vipgolfer", 405.0, 0.0, payout_cents=4000, is_cashing=True, is_vip=True),
            _standing(3, "g3", "eagle_eye", 398.25, 0.0, payout_cents=4000, is_cashing=True),
            _standing(41, "g4", "bogey_free", 371.0, 0.0),
            _standing(42, "g5", "scrambler", 368.5, 0.0),
        ],
        "vip_lineups": [
            {
                "display_name": "vipgolfer",
                "entry_key": "g2",
                "vip_entry_key": "g2",
                "rank": 2,
                "points": 405.0,
                "pmr": 0.0,
                "players_live": slots,
            }
        ],
        "train_clusters": [],
        "ownership": {
            "non_cashing_user_count": 58,
            "non_cashing_avg_pmr": 0.0,
            "non_cashing_top_remaining_players": [],
            "top_remaining_players": [],
            "watchlist_entries": [],
            "field_remaining_pct": None,
            "field_remaining_is_partial": False,
            "vip_remaining_by_entry_key": {},
            "vip_remaining_is_partial_by_entry_key": {},
            "avg_salary_per_player_remaining": None,
        },
        "cash_line": {"cutoff_type": "positions_paid", "rank": 40, "points": 372.75},
    }


SCENARIOS: tuple[Scenario, ...] = (Scenario("golf", "GOLF", 300100, _golf_bundle),)
