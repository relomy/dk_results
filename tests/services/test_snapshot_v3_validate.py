from copy import deepcopy

from dk_results.services.snapshot_v3.validate import validate_v3_envelope


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
                            "distance_to_cash": {
                                "per_vip": [{"vip_entry_key": "v1", "points_delta": 1.5}]
                            },
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


def test_validate_v3_envelope_accepts_valid_payload() -> None:
    assert validate_v3_envelope(_valid_envelope()) == []


def test_validate_v3_envelope_requires_top_level_timestamp_fields_and_non_empty_sports() -> None:
    payload = _valid_envelope()
    payload.pop("snapshot_at")
    payload.pop("generated_at")
    payload["sports"] = {}
    violations = validate_v3_envelope(payload)
    assert "snapshot_at is required" in violations
    assert "generated_at is required" in violations
    assert "sports must contain at least one sport payload" in violations


def test_validate_v3_envelope_enforces_contest_required_fields_and_types() -> None:
    base = _valid_envelope()
    required_fields = {
        "contest_id": "188080404",
        "contest_key": "nba:188080404",
        "name": "NBA Contest",
        "sport": "nba",
        "contest_type": "classic",
        "start_time": "2026-02-15T01:00:00Z",
        "state": "live",
        "entry_fee_cents": 1000,
        "prize_pool_cents": 200000,
        "currency": "USD",
        "max_entries": 229,
    }

    for field, valid_value in required_fields.items():
        payload_missing = deepcopy(base)
        payload_missing["sports"]["nba"]["contests"][0].pop(field, None)
        violations_missing = validate_v3_envelope(payload_missing)
        assert any(
            violation.endswith(f"contests[0].{field} is required") for violation in violations_missing
        ), field

        payload_bad_type = deepcopy(base)
        payload_bad_type["sports"]["nba"]["contests"][0][field] = [] if isinstance(valid_value, str) else "bad"
        violations_bad_type = validate_v3_envelope(payload_bad_type)
        assert any(
            violation.endswith(f"contests[0].{field} has invalid type") for violation in violations_bad_type
        ), field


def test_validate_v3_envelope_requires_exactly_one_contest() -> None:
    payload = _valid_envelope()
    payload["sports"]["nba"]["contests"] = []
    assert "sports.nba.contests must contain exactly 1 contest" in validate_v3_envelope(payload)


def test_validate_v3_envelope_detects_mixed_contest_ids_across_sections() -> None:
    payload = _valid_envelope()
    payload["sports"]["nba"]["contests"][0]["vip_lineups"][0]["contest_id"] = "different"
    violations = validate_v3_envelope(payload)
    assert "sports.nba.contests[0].vip_lineups[0].contest_id must match contest_id" in violations


def test_validate_v3_envelope_detects_duplicate_player_keys() -> None:
    payload = _valid_envelope()
    payload["sports"]["nba"]["contests"][0]["metrics"]["threat"]["top_swing_players"].append(
        {"player_key": "nba:1", "player_name": "Player A Dup"}
    )
    violations = validate_v3_envelope(payload)
    assert "sports.nba.contests[0].metrics.threat.top_swing_players has duplicate player_key nba:1" in violations


def test_validate_v3_envelope_detects_primary_contest_key_mismatch() -> None:
    payload = _valid_envelope()
    payload["sports"]["nba"]["primary_contest"]["contest_key"] = "nba:other"
    violations = validate_v3_envelope(payload)
    assert "sports.nba.primary_contest.contest_key must match contests[0].contest_key" in violations


def test_validate_v3_envelope_detects_unknown_threat_player_key() -> None:
    payload = _valid_envelope()
    payload["sports"]["nba"]["contests"][0]["metrics"]["threat"]["top_swing_players"][0]["player_key"] = "nba:999"
    violations = validate_v3_envelope(payload)
    assert (
        "sports.nba.contests[0].metrics.threat.top_swing_players[0].player_key "
        "is not in known contest player set"
    ) in violations


def test_validate_v3_envelope_detects_unknown_train_sample_entry_reference() -> None:
    payload = _valid_envelope()
    payload["sports"]["nba"]["contests"][0]["train_clusters"] = [
        {
            "cluster_key": "cluster-1",
            "entry_keys": ["e1", "unknown-entry"],
            "sample_entries": [{"entry_key": "unknown-entry"}],
        }
    ]
    violations = validate_v3_envelope(payload)
    assert (
        "sports.nba.contests[0].train_clusters[0].entry_keys "
        "contains unknown standings entry_key unknown-entry"
    ) in violations
    assert (
        "sports.nba.contests[0].train_clusters[0].sample_entries[0].entry_key must match standings entry_key"
        in violations
    )
