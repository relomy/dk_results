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


def _team_player(
    name: str, position: str, salary: int, team: str, status: str, own: float, *, sport: str, fpts: float = 0.0
) -> dict[str, Any]:
    return {
        "name": name,
        "player_key": f"{sport}:{name.lower().replace(' ', '-')}",
        "position": position,
        "roster_positions": [position],
        "salary": salary,
        "team": team,
        "game_status": status,
        "ownership_pct": own,
        "fantasy_points": fpts,
        "value": round(fpts / (salary / 1000), 2) if salary else 0.0,
    }


def _zero_vip_bundle() -> dict[str, Any]:
    """NBA with no tracked VIP: field-level metrics are emitted, VIP metrics are not."""
    final, live, pregame = "Final", "In Progress", "LAL@BOS 07:30PM ET"
    players = [
        _team_player("Nikola Jokic", "C", 12000, "DEN", final, 41.0, sport="nba", fpts=58.5),
        _team_player("Luka Doncic", "PG", 11500, "DAL", live, 38.5, sport="nba", fpts=31.25),
        _team_player("Jayson Tatum", "SF", 9800, "BOS", live, 27.0, sport="nba", fpts=22.0),
        _team_player("Anthony Davis", "PF", 9400, "LAL", pregame, 24.5, sport="nba"),
        _team_player("Jalen Brunson", "PG", 8600, "NYK", pregame, 19.0, sport="nba"),
        _team_player("Derrick White", "SG", 5400, "BOS", live, 12.5, sport="nba", fpts=14.5),
    ]
    return {
        "sport": "NBA",
        "contest": {
            "contest_id": "300200",
            "name": "NBA $5 Double Up",
            "sport": "nba",
            "contest_type": "classic",
            "start_time_utc": "2026-10-04T23:00:00Z",
            "state": "live",
            "entry_fee": 5,
            "prize_pool": 450,
            "currency": "USD",
            "max_entries": 100,
            "max_entries_per_user": 1,
        },
        "selected_contest_id": "300200",
        "selection_reason": {"mode": "explicit_id", "criteria": {"contest_id": "300200"}},
        "players": players,
        "standings": [
            _standing(
                1,
                "z1",
                "hoopsfan",
                281.5,
                96.0,
                payout_cents=1000,
                is_cashing=True,
                ownership_remaining_total_pct=18.5,
                remaining_salary=1200,
            ),
            _standing(
                2,
                "z2",
                "tripledouble",
                276.25,
                120.0,
                payout_cents=1000,
                is_cashing=True,
                ownership_remaining_total_pct=31.0,
                remaining_salary=0,
            ),
            _standing(
                44,
                "z3",
                "midrange",
                201.0,
                180.0,
                payout_cents=1000,
                is_cashing=True,
                ownership_remaining_total_pct=42.5,
                remaining_salary=800,
            ),
            _standing(
                45, "z4", "buzzerbeater", 198.75, 210.0, ownership_remaining_total_pct=55.0, remaining_salary=2400
            ),
        ],
        "vip_lineups": [],
        "train_clusters": [],
        "ownership": {
            "non_cashing_user_count": 56,
            "non_cashing_avg_pmr": 187.456,
            "non_cashing_top_remaining_players": [
                {"player_key": "nba:jayson-tatum", "player_name": "Jayson Tatum", "ownership_remaining_pct": 62.5},
                {"player_key": "nba:anthony-davis", "player_name": "Anthony Davis", "ownership_remaining_pct": 41.1},
            ],
            "top_remaining_players": [
                {"player_key": "nba:jayson-tatum", "player_name": "Jayson Tatum", "ownership_remaining_pct": 62.5},
                {"player_key": "nba:anthony-davis", "player_name": "Anthony Davis", "ownership_remaining_pct": 41.1},
            ],
            "watchlist_entries": [
                {
                    "entry_key": "z4",
                    "display_name": "buzzerbeater",
                    "ownership_remaining_pct": 55.0,
                    "current_rank": 45,
                    "current_points": 198.75,
                    "pmr": 210.0,
                },
                {
                    "entry_key": "z3",
                    "display_name": "midrange",
                    "ownership_remaining_pct": 42.5,
                    "current_rank": 44,
                    "current_points": 201.0,
                    "pmr": 180.0,
                },
            ],
            "ownership_remaining_total_pct": 36.75,
            "field_remaining_pct": 36.754,
            "field_remaining_is_partial": False,
            "vip_remaining_by_entry_key": {},
            "vip_remaining_is_partial_by_entry_key": {},
            "avg_salary_per_player_remaining": 6543.219,
        },
        "cash_line": {"cutoff_type": "positions_paid", "rank": 44, "points": 201.0},
    }


def _mlb_bundle() -> dict[str, Any]:
    """MLB: Game status present, but no non-cashing player tally and so no swing players."""
    final, live, pregame = "Final", "In Progress", "NYY@BOS 07:10PM ET"
    pool = [
        ("Shohei Ohtani", "OF", 6200, "LAD", final, 35.0, 24.0),
        ("Aaron Judge", "OF", 5900, "NYY", live, 28.5, 9.0),
        ("Mookie Betts", "SS", 5300, "LAD", final, 22.0, 6.0),
        ("Juan Soto", "OF", 5600, "NYM", pregame, 18.0, 0.0),
        ("Gerrit Cole", "SP", 9800, "NYY", live, 31.0, 12.5),
        ("Corbin Burnes", "SP", 9400, "BAL", pregame, 26.0, 0.0),
    ]
    players = [
        _team_player(name, pos, salary, team, status, own, sport="mlb", fpts=fpts)
        for name, pos, salary, team, status, own, fpts in pool
    ]
    by_name = {p["name"]: p for p in players}

    def slot(label: str, name: str) -> dict[str, Any]:
        player = by_name[name]
        return _slot(label, name, player["player_key"], player["salary"], live=player["game_status"] == live)

    return {
        "sport": "MLB",
        "contest": {
            "contest_id": "300300",
            "name": "MLB $10 Double Up",
            "sport": "mlb",
            "contest_type": "classic",
            "start_time_utc": "2026-09-20T23:05:00Z",
            "state": "live",
            "entry_fee": 10,
            "prize_pool": 900,
            "currency": "USD",
            "max_entries": 100,
            "max_entries_per_user": 3,
        },
        "selected_contest_id": "300300",
        "selection_reason": {"mode": "explicit_id", "criteria": {"contest_id": "300300"}},
        "players": players,
        "standings": [
            _standing(
                1,
                "m1",
                "dingerking",
                142.5,
                64.0,
                payout_cents=2000,
                is_cashing=True,
                ownership_remaining_total_pct=44.0,
                remaining_salary=500,
            ),
            _standing(
                17,
                "m2",
                "vipslugger",
                118.25,
                88.0,
                payout_cents=2000,
                is_cashing=True,
                ownership_remaining_total_pct=51.5,
                remaining_salary=0,
                is_vip=True,
            ),
            _standing(
                18,
                "m3",
                "bullpenbaron",
                118.25,
                88.0,
                payout_cents=2000,
                is_cashing=True,
                ownership_remaining_total_pct=51.5,
                remaining_salary=0,
            ),
            _standing(61, "m4", "closerzone", 96.0, 140.0, ownership_remaining_total_pct=63.0, remaining_salary=1800),
        ],
        "vip_lineups": [
            {
                "display_name": "vipslugger",
                "entry_key": "m2",
                "vip_entry_key": "m2",
                "rank": 17,
                "points": 118.25,
                "pmr": 88.0,
                "players_live": [
                    slot("SP", "Gerrit Cole"),
                    slot("OF", "Shohei Ohtani"),
                    slot("OF", "Aaron Judge"),
                    slot("SS", "Mookie Betts"),
                    {"slot": "OF", "player_name": "LOCKED \N{LOCK}", "is_locked": True},
                ],
            }
        ],
        "train_clusters": [
            {
                "cluster_id": "5c1b7d0e9a",
                "cluster_rule": "salary_remaining<=40000_and_same_points_pmr",
                "user_count": 2,
                "rank": 17,
                "points": 118.25,
                "pmr": 88.0,
                "lineup_signature": "mlb:gerrit-cole|mlb:mookie-betts|mlb:shohei-ohtani",
                "entry_keys": ["m2", "m3"],
            }
        ],
        "ownership": {
            "non_cashing_user_count": 82,
            "non_cashing_avg_pmr": 151.2,
            "non_cashing_top_remaining_players": [],
            "top_remaining_players": [],
            "watchlist_entries": [
                {
                    "entry_key": "m4",
                    "display_name": "closerzone",
                    "ownership_remaining_pct": 63.0,
                    "current_rank": 61,
                    "current_points": 96.0,
                    "pmr": 140.0,
                }
            ],
            "ownership_remaining_total_pct": 52.5,
            "field_remaining_pct": 52.5,
            "field_remaining_is_partial": False,
            "vip_remaining_by_entry_key": {"m2": 40.25},
            "vip_remaining_is_partial_by_entry_key": {"m2": True},
            "avg_salary_per_player_remaining": 6120.5,
        },
        "cash_line": {"cutoff_type": "positions_paid", "rank": 18, "points": 118.25},
    }


SCENARIOS: tuple[Scenario, ...] = (
    Scenario("golf", "GOLF", 300100, _golf_bundle),
    Scenario("zero_vip", "NBA", 300200, _zero_vip_bundle),
    Scenario("mlb", "MLB", 300300, _mlb_bundle),
)
