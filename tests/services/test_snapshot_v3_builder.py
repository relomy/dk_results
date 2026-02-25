from dk_results.services.snapshot_v3.builder import build_sport_payload


def _raw_bundle_seed() -> dict:
    return {
        "sport": "NBA",
        "contest": {
            "contest_id": "188080404",
            "name": "NBA Single Entry $10 Double Up",
            "sport": "nba",
            "contest_type": "classic",
            "start_time_utc": "2026-02-15T01:00:00Z",
            "state": "live",
            "entry_fee": 10,
            "prize_pool": 2000,
            "currency": "USD",
            "entries": 229,
            "max_entries_per_user": 1,
        },
        "selected_contest_id": "188080404",
        "selection_reason": {"mode": "explicit_id", "criteria": {"contest_id": "188080404"}},
        "players": [{"name": "A"}],
        "standings": [{"entry_key": "e1"}],
        "vip_lineups": [{"entry_key": "e1"}],
        "train_clusters": [],
        "ownership": {"watchlist_entries": []},
        "cash_line": {"cutoff_type": "positions_paid", "rank": 60, "points": 250.5},
    }


def test_builder_creates_single_contest_sport_payload_with_required_fields() -> None:
    raw = _raw_bundle_seed()
    payload = build_sport_payload(
        raw,
        derived={
            "avg_salary_per_player_remaining": 6158.0,
            "distance_to_cash": {
                "cutoff_points": 250.5,
                "per_vip": [{"vip_entry_key": "v1", "points_delta": 3.25}],
            },
            "threat": {"top_swing_players": [{"player_key": "nba:1", "player_name": "A"}]},
        },
        generated_at="2026-02-25T10:11:12Z",
    )

    assert payload["status"] == "ok"
    assert payload["updated_at"] == "2026-02-25T10:11:12Z"
    assert payload["primary_contest"]["contest_id"] == "188080404"
    assert payload["primary_contest"]["contest_key"] == "nba:188080404"
    assert len(payload["contests"]) == 1

    contest = payload["contests"][0]
    assert contest["contest_id"] == "188080404"
    assert contest["contest_key"] == "nba:188080404"
    assert contest["name"] == "NBA Single Entry $10 Double Up"
    assert contest["sport"] == "nba"
    assert contest["contest_type"] == "classic"
    assert contest["start_time"] == "2026-02-15T01:00:00Z"
    assert contest["state"] == "live"
    assert contest["entry_fee_cents"] == 1000
    assert contest["prize_pool_cents"] == 200000
    assert contest["currency"] == "USD"
    assert contest["max_entries"] == 229
    assert contest["max_entries_per_user"] == 1


def test_builder_places_live_metrics_and_metrics_and_omits_unavailable_sections() -> None:
    raw = _raw_bundle_seed()

    payload = build_sport_payload(
        raw,
        derived={
            "avg_salary_per_player_remaining": 6158.0,
            "distance_to_cash": None,
            "threat": {"top_swing_players": [{"player_key": "nba:1", "player_name": "A"}]},
        },
        generated_at="2026-02-25T10:11:12Z",
    )

    contest = payload["contests"][0]
    assert "live_metrics" in contest
    assert contest["live_metrics"]["cash_line"]["points_cutoff"] == 250.5
    assert contest["live_metrics"]["avg_salary_per_player_remaining"] == 6158.0
    assert "metrics" in contest
    assert "distance_to_cash" not in contest["metrics"]
    assert "threat" in contest["metrics"]

    payload_without_metrics = build_sport_payload(
        {**raw, "cash_line": {}},
        derived={
            "avg_salary_per_player_remaining": None,
            "distance_to_cash": None,
            "threat": None,
        },
        generated_at="2026-02-25T10:11:12Z",
    )
    contest_without_metrics = payload_without_metrics["contests"][0]
    assert "live_metrics" not in contest_without_metrics
    assert "metrics" not in contest_without_metrics
