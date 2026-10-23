"""Shared envelope and contest builders for the snapshot validator tests."""

from copy import deepcopy


def _valid_envelope() -> dict:
    return {
        "schema_version": 3,
        "snapshot_at": "2026-02-25T10:00:00Z",
        "generated_at": "2026-02-25T10:00:00Z",
        "sports": {
            "nba": {
                "status": "ok",
                "updated_at": "2026-02-25T10:00:00Z",
                "players": [{"name": "A", "player_key": "nba:1"}],
                "primary_contest": {
                    "contest_id": "188080404",
                    "contest_key": "nba:188080404",
                    "selection_reason": {"mode": "explicit_id"},
                    "selected_at": "2026-02-25T10:00:00Z",
                },
                "contests": [
                    {
                        "contest_id": "188080404",
                        "contest_key": "nba:188080404",
                        "name": "NBA Single Entry $10 Double Up",
                        "sport": "nba",
                        "contest_type": "classic",
                        "start_time": "2026-02-15T01:00:00Z",
                        "state": "live",
                        "entry_fee_cents": 1000,
                        "prize_pool_cents": 200000,
                        "currency": "USD",
                        "max_entries": 229,
                        "standings": [{"entry_key": "e1", "contest_id": "188080404"}],
                        "vip_lineups": [{"display_name": "vip1", "contest_id": "188080404"}],
                        "train_clusters": [{"cluster_key": "c1", "contest_id": "188080404"}],
                        "metrics": {
                            "updated_at": "2026-02-25T10:00:00Z",
                            "distance_to_cash": {"per_vip": [{"vip_entry_key": "v1", "points_delta": 1.5}]},
                            "threat": {
                                "top_swing_players": [
                                    {
                                        "player_key": "nba:1",
                                        "player_name": "Player A",
                                        "ownership_remaining_pct": 80.0,
                                    }
                                ]
                            },
                        },
                    }
                ],
            }
        },
    }


def _valid_contest() -> dict:
    return deepcopy(_valid_envelope()["sports"]["nba"]["contests"][0])
