"""Scenario bundles behind the golden envelopes (see ``test_snapshot_v3_goldens.py``).

Add a scenario with one bundle builder and one ``SCENARIOS`` entry; its golden is
written by the regenerate command documented in ``docs/TESTING.md``.
"""

from __future__ import annotations

import csv
import tempfile
from collections.abc import Callable
from contextlib import ExitStack
from copy import deepcopy
from dataclasses import dataclass
from typing import Any
from unittest.mock import patch

from dk_results.persistence.contestdatabase import ContestRow
from dk_results.services.snapshot_v3 import collector
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
            "positions_paid": 40,
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
            "positions_paid": 44,
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
            "positions_paid": 18,
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


# --- NFL mid-slate: the quirks prod showed on 2026-10-04, fed through the real collector --------------


class _NflDraftKings:
    """DraftKings edge stub serving raw payloads: salary CSV, standings CSV rows, leaderboard, VIP scorecards."""

    def __init__(self, standings_rows: list[list[str]], leaderboard: dict[str, Any], scorecards: dict[str, list]):
        self._standings_rows = standings_rows
        self._leaderboard = leaderboard
        self._scorecards = scorecards

    def get_leaderboard(self, _contest_id: int, *, timeout: int | None = None) -> dict[str, Any]:
        return self._leaderboard

    def get_draftables(self, _draft_group: int, timeout: int | None = None) -> dict[str, Any]:
        return {"draftables": [], "competitions": []}

    def download_salary_csv(self, _sport: str, _draft_group: int, path: str) -> None:
        with open(path, "w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["Position", "Name", "Roster Position", "Salary", "Game Info", "TeamAbbrev"])
            for name, (pos, salary, team, status, _own, _fpts) in _NFL_POOL.items():
                writer.writerow([pos, name, _NFL_FLEX_ELIGIBLE.get(pos, pos), salary, status, team])

    def download_contest_rows(self, *_args: Any, **_kwargs: Any) -> list[list[str]]:
        return self._standings_rows

    def get_entry(self, _draft_group: int, entry_key: str, *, timeout: int | None = None, session: Any = None):
        return {"entries": [{"roster": {"scorecards": self._scorecards[entry_key]}}]}

    def clone_auth_to(self, _session: Any) -> None:
        return None


class _NflContestDatabase:
    def __init__(self, row: ContestRow):
        self._row = row

    def get_live_contest_candidates(self, *_args: Any, **_kwargs: Any) -> list[tuple]:
        return []

    def get_contest_by_id(self, _contest_id: int) -> ContestRow:
        return self._row

    def get_contest_state(self, _dk_id: int) -> None:
        return None

    def get_contest_contract_metadata(self, _dk_id: int) -> None:
        return None


_NFL_FINAL, _NFL_LIVE, _NFL_PREGAME = "Final", "In Progress", "DAL@PHI 08:20PM ET"
_NFL_FLEX_ELIGIBLE = {"RB": "RB/FLEX", "WR": "WR/FLEX", "TE": "TE/FLEX"}
# name -> (position, salary, team, game status, field ownership %, fantasy points)
_NFL_POOL: dict[str, tuple[str, int, str, str, float, float]] = {
    "Josh Allen": ("QB", 7800, "BUF", _NFL_FINAL, 14.0, 21.5),
    "Patrick Mahomes": ("QB", 7600, "KC", _NFL_LIVE, 18.5, 14.2),
    "Jalen Hurts": ("QB", 7300, "PHI", _NFL_PREGAME, 12.0, 0.0),
    "Derrick Henry": ("RB", 7400, "BAL", _NFL_FINAL, 22.0, 25.4),
    "Bijan Robinson": ("RB", 7100, "ATL", _NFL_LIVE, 17.5, 8.1),
    "Saquon Barkley": ("RB", 8000, "PHI", _NFL_PREGAME, 24.0, 0.0),
    "James Cook": ("RB", 6000, "BUF", _NFL_FINAL, 15.0, 11.3),
    "Justin Jefferson": ("WR", 7900, "MIN", _NFL_FINAL, 19.0, 18.7),
    "Ja'Marr Chase": ("WR", 8400, "CIN", _NFL_LIVE, 26.5, 12.2),
    "Puka Nacua": ("WR", 7200, "LAR", _NFL_LIVE, 21.0, 9.4),
    "CeeDee Lamb": ("WR", 8000, "DAL", _NFL_PREGAME, 20.0, 0.0),
    "Ladd McConkey": ("WR", 5400, "LAC", _NFL_LIVE, 6.0, 7.5),
    "Amon-Ra St. Brown": ("WR", 7500, "DET", _NFL_FINAL, 16.0, 14.6),
    "Travis Kelce": ("TE", 5600, "KC", _NFL_LIVE, 13.5, 6.8),
    "Sam LaPorta": ("TE", 4600, "DET", _NFL_FINAL, 9.0, 10.2),
    "Rams": ("DST", 3200, "LAR", _NFL_LIVE, 12.5, 7.0),
    "Jets": ("DST", 2800, "NYJ", _NFL_FINAL, 8.0, 9.0),
    "Eagles": ("DST", 3400, "PHI", _NFL_PREGAME, 15.0, 0.0),
}
_NFL_SLOTS = ("QB", "RB", "RB", "WR", "WR", "WR", "TE", "FLEX", "DST")
# Lineups as names in slot order. Pregame players are hidden (LOCKED) until their game starts.
_NFL_LINEUPS: dict[str, tuple[str, ...]] = {
    # Mostly finished games.
    "A": (
        "Josh Allen",
        "Derrick Henry",
        "James Cook",
        "Justin Jefferson",
        "Ja'Marr Chase",
        "Amon-Ra St. Brown",
        "Sam LaPorta",
        "Puka Nacua",
        "Jets",
    ),
    # Rosters Ladd McConkey, whom no non-cashing lineup does: a tied cashing row miscounted as
    # non-cashing would surface him in the non-cashing tally.
    "T": (
        "Josh Allen",
        "Derrick Henry",
        "James Cook",
        "Justin Jefferson",
        "Ladd McConkey",
        "Amon-Ra St. Brown",
        "Sam LaPorta",
        "Bijan Robinson",
        "Jets",
    ),
    "B": (
        "Patrick Mahomes",
        "Derrick Henry",
        "Bijan Robinson",
        "Justin Jefferson",
        "Ja'Marr Chase",
        "Puka Nacua",
        "Travis Kelce",
        "James Cook",
        "Rams",
    ),
    "C": (
        "Patrick Mahomes",
        "Bijan Robinson",
        "James Cook",
        "Ja'Marr Chase",
        "Puka Nacua",
        "Justin Jefferson",
        "Travis Kelce",
        "Derrick Henry",
        "Rams",
    ),
    "D": (
        "Jalen Hurts",
        "Saquon Barkley",
        "Bijan Robinson",
        "CeeDee Lamb",
        "Ja'Marr Chase",
        "Puka Nacua",
        "Travis Kelce",
        "Sam LaPorta",
        "Eagles",
    ),
    "E": (
        "Josh Allen",
        "Saquon Barkley",
        "Derrick Henry",
        "CeeDee Lamb",
        "Puka Nacua",
        "Amon-Ra St. Brown",
        "Travis Kelce",
        "James Cook",
        "Rams",
    ),
    "F": (
        "Jalen Hurts",
        "Bijan Robinson",
        "James Cook",
        "Ja'Marr Chase",
        "Puka Nacua",
        "Justin Jefferson",
        "Travis Kelce",
        "Derrick Henry",
        "Rams",
    ),
    "G": (
        "Josh Allen",
        "Derrick Henry",
        "James Cook",
        "Justin Jefferson",
        "Ja'Marr Chase",
        "CeeDee Lamb",
        "Sam LaPorta",
        "Saquon Barkley",
        "Jets",
    ),
}
# DraftKings hands VIP scorecards back with the defense's name padded.
_NFL_PADDED_DST = {"Rams": "Rams ", "Jets": "Jets "}
# (rank, entry, user, pmr, points, lineup). Ties inside the cash line (2, 5) and at it (10), rows out of score
# order, 10 paid positions of 20 entries: 11 rows cash, 9 do not. Ranks 8, 10, 13 and 17 are the tracked VIPs.
_NFL_VIPS = ("EmpireMaker2", "vip_at_line", "vip_below_a", "vip_below_b")
_NFL_ENTRIES = (
    ("2", "e03", "tied_top_b", "300", "170.04", "T"),
    ("1", "e01", "leader", "240", "188.52", "A"),
    ("5", "e07", "triple_c", "420", "152.26", "T"),
    ("2", "e02", "tied_top_a", "300", "170.04", "T"),
    ("4", "e04", "chaser", "360", "165.5", "B"),
    ("10", "e11", "line_b", "510", "128.02", "A"),
    ("5", "e05", "triple_a", "420", "152.26", "T"),
    ("9", "e09", "ninth", "480", "133.5", "B"),
    ("8", "e08", "EmpireMaker2", "480", "141.0", "E"),
    ("10", "e10", "vip_at_line", "510", "128.02", "G"),
    ("5", "e06", "triple_b", "420", "152.26", "T"),
    ("14", "e14", "tied_low_a", "570", "110.5", "C"),
    ("12", "e12", "just_out", "540", "119.76", "C"),
    ("13", "e13", "vip_below_a", "540", "116.0", "D"),
    ("20", "e20", "last", "600", "55.5", "E"),
    ("14", "e15", "tied_low_b", "570", "110.5", "E"),
    ("16", "e16", "sixteenth", "570", "98.0", "B"),
    ("19", "e19", "nineteenth", "600", "70.0", "D"),
    ("17", "e17", "vip_below_b", "600", "92.5", "F"),
    ("18", "e18", "eighteenth", "600", "80.0", "C"),
)
_NFL_STANDINGS_LIMIT = 6
_NFL_CASH_PAYOUTS = {"e10": "50.00", "e11": "50.00"}  # tied at the line: positions 10 and 11 share one $100 payout


def _nfl_lineup_string(lineup: str) -> str:
    tokens = []
    for slot, name in zip(_NFL_SLOTS, _NFL_LINEUPS[lineup], strict=True):
        hidden = _NFL_POOL[name][3] == _NFL_PREGAME
        tokens.append(f"{slot} {'LOCKED' if hidden else name}")
    return " ".join(tokens)


def _nfl_standings_rows() -> list[list[str]]:
    header = ["rank", "entry", "name", "pmr", "points", "lineup", "", "player", "position", "ownership", "fpts"]
    stats = [[name, pool[0], f"{pool[4]}%", str(pool[5])] for name, pool in _NFL_POOL.items()]
    rows = [header]
    for index, (rank, entry, user, pmr, points, lineup) in enumerate(_NFL_ENTRIES):
        rows.append(
            [
                rank,
                entry,
                user,
                pmr,
                points,
                _nfl_lineup_string(lineup),
                "",
                *(stats[index] if index < len(stats) else []),
            ]
        )
    return rows


def _nfl_scorecards(lineup: str) -> list[dict[str, Any]]:
    cards = []
    for slot, name in zip(_NFL_SLOTS, _NFL_LINEUPS[lineup], strict=True):
        _pos, _salary, _team, status, own, fpts = _NFL_POOL[name]
        if status == _NFL_PREGAME:
            cards.append({"rosterPosition": slot, "displayName": "", "score": "", "timeRemaining": "60"})
            continue
        cards.append(
            {
                "rosterPosition": slot,
                "displayName": _NFL_PADDED_DST.get(name, name),
                "score": fpts,
                "percentDrafted": own,
                "timeRemaining": "0" if status == _NFL_FINAL else "35",
                "projection": {"realTimeProjection": fpts, "pregameProjection": fpts},
            }
        )
    return cards


def _nfl_leaderboard() -> dict[str, Any]:
    paid = [entry for _rank, entry, *_rest in _NFL_ENTRIES if int(entry[1:]) <= 11]
    return {
        "contestStandings": [
            {
                "entryKey": entry,
                "winnings": [{"payoutType": "CASH", "winningValue": _NFL_CASH_PAYOUTS.get(entry, "100.00")}],
            }
            for entry in paid
        ]
    }


def _nfl_mid_slate_bundle() -> dict[str, Any]:
    """NFL Double Up mid-slate through the real collector, with DraftKings and the contest DB stubbed.

    Quirks (relomy/dk_results#178, #179): VIPs ranked beyond the 6-row standings cut whose rank and PMR
    arrive as strings, a defense named ``"Rams "`` on DraftKings scorecards, hidden (locked) slots, and ties
    inside and at the cash line.
    """
    row = ContestRow(
        dk_id=300400,
        name="NFL $50 Double Up [Single Entry]",
        draft_group=154300,
        positions_paid=10,
        start_date="2026-10-04T13:00:00",
        entry_fee=50,
        entries=20,
        contest_state="live",
        prize_pool=1000,
        max_entries_per_user=1,
    )
    vip_lineups = {entry: lineup for _rank, entry, user, _pmr, _pts, lineup in _NFL_ENTRIES if user in _NFL_VIPS}
    dk = _NflDraftKings(
        _nfl_standings_rows(),
        _nfl_leaderboard(),
        {entry: _nfl_scorecards(lineup) for entry, lineup in vip_lineups.items()},
    )
    real_collect = collector._collect_source_snapshot
    with ExitStack() as stack:
        stack.enter_context(patch.object(collector, "SALARY_DIR", stack.enter_context(tempfile.TemporaryDirectory())))
        stack.enter_context(patch.object(collector, "load_vips", lambda: list(_NFL_VIPS)))
        stack.enter_context(
            patch.object(
                collector,
                "_collect_source_snapshot",
                lambda **kwargs: real_collect(dk=dk, contest_db=_NflContestDatabase(row), **kwargs),
            )
        )
        return collector.collect_snapshot(sport="NFL", contest_id=300400, standings_limit=_NFL_STANDINGS_LIMIT).bundle


SCENARIOS: tuple[Scenario, ...] = (
    Scenario("golf", "GOLF", 300100, _golf_bundle),
    Scenario("zero_vip", "NBA", 300200, _zero_vip_bundle),
    Scenario("mlb", "MLB", 300300, _mlb_bundle),
    Scenario("nfl_mid_slate", "NFL", 300400, _nfl_mid_slate_bundle),
)
