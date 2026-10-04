"""Field-level contest metrics through the snapshot envelope pipeline.

A fake collector returns a hand-built bundle; the real builder and validator
run, and assertions read the emitted envelope the way the dashboard does.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

from dk_results.services.snapshot_v3.pipeline import build_snapshot_v3_envelope

GENERATED_AT = "2026-10-04T12:00:00Z"


def _player(name: str, status: str, *, salary: int = 5000) -> dict[str, Any]:
    return {
        "name": name,
        "player_key": f"x:{name.lower()}",
        "position": "UTIL",
        "salary": salary,
        "team": "AAA",
        "game_status": status,
        "ownership_pct": 10.0,
    }


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


def _contest(bundle: dict[str, Any]) -> dict[str, Any]:
    envelope = build_snapshot_v3_envelope(
        {bundle["sport"]: 900},
        generated_at=GENERATED_AT,
        collector=lambda **_: deepcopy(bundle),
    )
    return envelope["sports"][bundle["sport"].lower()]["contests"][0]


def _non_cashing_bundle(sport: str = "NBA") -> dict[str, Any]:
    return _bundle(
        sport,
        non_cashing_user_count=40,
        non_cashing_avg_pmr=123.456,
        non_cashing_top_remaining_players=[
            {"player_name": "A", "player_key": "x:a", "ownership_remaining_pct": 62.5},
            {"player_name": "B", "player_key": "x:b", "ownership_remaining_pct": 30.0},
        ],
    )


class TestAverageSalaryRemaining:
    def test_emitted_for_live_contest_with_zero_vips(self) -> None:
        bundle = _bundle(avg_salary_per_player_remaining=6543.219)
        assert bundle["vip_lineups"] == []

        live_metrics = _contest(bundle)["live_metrics"]

        assert live_metrics["avg_salary_per_player_remaining"] == 6543.22

    def test_ignores_vip_slot_salaries(self) -> None:
        bundle = _bundle(avg_salary_per_player_remaining=6000.0)
        bundle["vip_lineups"] = [{"vip_entry_key": "v1", "entry_key": "e1", "lineup": [{"salary": 1, "is_live": True}]}]

        assert _contest(bundle)["live_metrics"]["avg_salary_per_player_remaining"] == 6000.0

    def test_omitted_when_collector_found_no_unfinished_slot(self) -> None:
        contest = _contest(_bundle(avg_salary_per_player_remaining=None))

        assert "live_metrics" not in contest

    def test_omitted_for_sport_with_no_game_status(self) -> None:
        bundle = _bundle("GOLF", avg_salary_per_player_remaining=7000.0)
        bundle["players"] = [_player("A", "Masters Tournament"), _player("B", "Masters Tournament")]

        assert "live_metrics" not in _contest(bundle)


class TestNonCashing:
    def test_emits_count_pmr_and_top_players_for_tallied_sport(self) -> None:
        non_cashing = _contest(_non_cashing_bundle("NBA"))["metrics"]["non_cashing"]

        assert non_cashing == {
            "users_not_cashing": 40,
            "avg_pmr_remaining": 123.46,
            "top_remaining_players": [
                {"player_name": "A", "ownership_remaining_pct": 62.5},
                {"player_name": "B", "ownership_remaining_pct": 30.0},
            ],
        }

    @pytest.mark.parametrize("sport", ["NFL", "NFLShowdown", "CFB", "NBA"])
    def test_tallied_sports_carry_top_remaining_players(self, sport: str) -> None:
        non_cashing = _contest(_non_cashing_bundle(sport))["metrics"]["non_cashing"]

        assert "top_remaining_players" in non_cashing

    def test_non_tallied_sport_omits_top_remaining_players(self) -> None:
        bundle = _non_cashing_bundle("MLB")
        bundle["ownership"]["non_cashing_top_remaining_players"] = []
        bundle["ownership"]["top_remaining_players"] = []

        non_cashing = _contest(bundle)["metrics"]["non_cashing"]

        assert non_cashing == {"users_not_cashing": 40, "avg_pmr_remaining": 123.46}


class TestNoGameStatus:
    @pytest.mark.parametrize("sport", ["GOLF", "NBA"])
    def test_no_status_pool_omits_all_ownership_remaining_outputs(self, sport: str) -> None:
        bundle = _non_cashing_bundle(sport)
        bundle["players"] = [_player("A", "Masters Tournament"), _player("B", "Masters Tournament")]
        bundle["ownership"].update(
            avg_salary_per_player_remaining=7000.0,
            field_remaining_pct=60.0,
            field_remaining_is_partial=False,
            vip_remaining_by_entry_key={"e1": 50.0},
            ownership_remaining_total_pct=60.0,
            watchlist_entries=[{"entry_key": "e1", "ownership_remaining_pct": 50.0}],
        )
        bundle["standings"] = [{"entry_key": "e1", "ownership_remaining_total_pct": 50.0}]
        bundle["vip_lineups"] = [
            {
                "vip_entry_key": "v1",
                "entry_key": "e1",
                "display_name": "VIP",
                "players_live": [
                    {"slot": "UTIL", "player_key": "x:a", "player_name": "A", "salary": 5000, "is_live": False}
                ],
            }
        ]

        contest = _contest(bundle)

        assert "ownership_remaining_total_pct" not in contest["standings"][0]
        assert "ownership_watchlist" not in contest
        assert "live_metrics" not in contest
        assert "threat" not in contest["metrics"]
        assert contest["metrics"]["non_cashing"] == {"users_not_cashing": 40, "avg_pmr_remaining": 123.46}
        summary = contest["metrics"]["ownership_summary"]["per_vip"][0]
        assert summary["total_ownership_pct"] == 10.0
        assert "ownership_in_play_pct" not in summary


class TestNonCashingAvailability:
    def test_top_remaining_players_capped_at_ten(self) -> None:
        bundle = _non_cashing_bundle("NBA")
        bundle["players"] += [_player(f"P{i}", "Final") for i in range(12)]
        bundle["ownership"]["non_cashing_top_remaining_players"] = [
            {"player_name": f"P{i}", "player_key": f"x:p{i}", "ownership_remaining_pct": 50.0 - i} for i in range(12)
        ]

        rows = _contest(bundle)["metrics"]["non_cashing"]["top_remaining_players"]

        assert [row["player_name"] for row in rows] == [f"P{i}" for i in range(10)]

    @pytest.mark.parametrize("users", [0, None])
    def test_omitted_when_no_user_is_non_cashing(self, users: Any) -> None:
        bundle = _non_cashing_bundle("NBA")
        bundle["ownership"]["non_cashing_user_count"] = users

        assert "non_cashing" not in _contest(bundle).get("metrics", {})

    def test_omitted_when_avg_pmr_missing(self) -> None:
        bundle = _non_cashing_bundle("NBA")
        bundle["ownership"]["non_cashing_avg_pmr"] = None

        assert "non_cashing" not in _contest(bundle).get("metrics", {})

    def test_emitted_for_golf_like_pool_without_game_status(self) -> None:
        bundle = _non_cashing_bundle("GOLF")
        bundle["players"] = [_player("A", "Masters Tournament"), _player("B", "Masters Tournament")]

        non_cashing = _contest(bundle)["metrics"]["non_cashing"]

        assert non_cashing == {"users_not_cashing": 40, "avg_pmr_remaining": 123.46}
