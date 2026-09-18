from copy import deepcopy

from dk_results.services.snapshot_v3.validate import (
    _collect_known_player_keys,
    _validate_section_rows,
    _validate_train_cluster_references,
    validate_v3_envelope,
)


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
        assert any(violation.endswith(f"contests[0].{field} is required") for violation in violations_missing), field

        payload_bad_type = deepcopy(base)
        payload_bad_type["sports"]["nba"]["contests"][0][field] = [] if isinstance(valid_value, str) else "bad"
        violations_bad_type = validate_v3_envelope(payload_bad_type)
        assert any(violation.endswith(f"contests[0].{field} has invalid type") for violation in violations_bad_type), (
            field
        )


def test_validate_v3_envelope_requires_exactly_one_contest() -> None:
    payload = _valid_envelope()
    payload["sports"]["nba"]["contests"] = []
    assert "sports.nba.contests must contain exactly 1 contest" in validate_v3_envelope(payload)


def test_validate_v3_envelope_reports_malformed_sport_rows() -> None:
    payload = _valid_envelope()
    sport_payload = payload["sports"]["nba"]
    sport_payload["players"] = [{"name": 12}, "not-an-object"]
    sport_payload["contests"] = [{"contest_id": "188080404"}, "not-an-object"]
    sport_payload["primary_contest"] = {"contest_id": "188080404"}

    violations = validate_v3_envelope(payload)

    assert "sports.nba.players[0].name has invalid type" in violations
    assert "sports.nba.players[1] must be an object" in violations
    assert "sports.nba.contests[1] must be an object" in violations
    assert "sports.nba.primary_contest.contest_key is required" in violations
    assert "sports.nba.primary_contest.selection_reason is required" in violations


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
        "sports.nba.contests[0].metrics.threat.top_swing_players[0].player_key is not in known contest player set"
    ) in violations


def test_validate_v3_envelope_allows_train_entry_keys_outside_truncated_standings() -> None:
    payload = _valid_envelope()
    payload["sports"]["nba"]["contests"][0]["train_clusters"] = [
        {
            "cluster_key": "cluster-1",
            "entry_keys": ["e1", "unknown-entry"],
            "sample_entries": [{"entry_key": "unknown-entry"}],
        }
    ]
    violations = validate_v3_envelope(payload)
    assert not any("train_clusters[0].entry_keys" in message for message in violations)
    assert not any("sample_entries[0].entry_key" in message for message in violations)


def test_validate_v3_envelope_detects_train_sample_entry_not_in_cluster_entries() -> None:
    payload = _valid_envelope()
    payload["sports"]["nba"]["contests"][0]["train_clusters"] = [
        {
            "cluster_key": "cluster-1",
            "entry_keys": ["e1", "e2"],
            "sample_entries": [{"entry_key": "e3"}],
        }
    ]
    violations = validate_v3_envelope(payload)
    assert (
        "sports.nba.contests[0].train_clusters[0].sample_entries[0].entry_key must match "
        "train_clusters[0].entry_keys" in violations
    )


def _valid_contest() -> dict:
    return deepcopy(_valid_envelope()["sports"]["nba"]["contests"][0])


# ── _validate_section_rows ───────────────────────────────────────────────────


def test_validate_section_rows_accepts_valid_contest() -> None:
    assert _validate_section_rows("nba", _valid_contest()) == []


def test_validate_section_rows_rejects_non_list_standings() -> None:
    contest = _valid_contest()
    contest["standings"] = "not-a-list"
    assert "sports.nba.contests[0].standings has invalid type" in _validate_section_rows("nba", contest)


def test_validate_section_rows_rejects_non_dict_row_in_section() -> None:
    contest = _valid_contest()
    contest["vip_lineups"] = ["not-a-dict"]
    assert "sports.nba.contests[0].vip_lineups[0] must be an object" in _validate_section_rows("nba", contest)


def test_validate_section_rows_rejects_non_dict_ownership_watchlist() -> None:
    contest = _valid_contest()
    contest["ownership_watchlist"] = "bad"
    assert "sports.nba.contests[0].ownership_watchlist has invalid type" in _validate_section_rows("nba", contest)


def test_validate_section_rows_rejects_non_dict_live_metrics() -> None:
    contest = _valid_contest()
    contest["live_metrics"] = "bad"
    assert "sports.nba.contests[0].live_metrics has invalid type" in _validate_section_rows("nba", contest)


def test_validate_section_rows_rejects_invalid_live_metrics_updated_at() -> None:
    contest = _valid_contest()
    contest["live_metrics"] = {"updated_at": "not-a-timestamp"}
    violations = _validate_section_rows("nba", contest)
    assert "sports.nba.contests[0].live_metrics.updated_at must be a valid ISO timestamp" in violations


def test_validate_section_rows_rejects_invalid_live_metrics_cash_line_type() -> None:
    contest = _valid_contest()
    contest["live_metrics"] = {"cash_line": "bad"}
    violations = _validate_section_rows("nba", contest)
    assert "sports.nba.contests[0].live_metrics.cash_line has invalid type" in violations


def test_validate_section_rows_rejects_invalid_metrics_updated_at() -> None:
    contest = _valid_contest()
    contest["metrics"]["updated_at"] = "not-a-timestamp"
    violations = _validate_section_rows("nba", contest)
    assert "sports.nba.contests[0].metrics.updated_at must be a valid ISO timestamp" in violations


def test_validate_section_rows_rejects_invalid_metrics_distance_to_cash_type() -> None:
    contest = _valid_contest()
    contest["metrics"]["distance_to_cash"] = "bad"
    violations = _validate_section_rows("nba", contest)
    assert "sports.nba.contests[0].metrics.distance_to_cash has invalid type" in violations


def test_validate_section_rows_rejects_invalid_metrics_threat_type() -> None:
    contest = _valid_contest()
    contest["metrics"]["threat"] = "bad"
    violations = _validate_section_rows("nba", contest)
    assert "sports.nba.contests[0].metrics.threat has invalid type" in violations


# ── _collect_known_player_keys ───────────────────────────────────────────────


def test_collect_known_player_keys_from_sport_players() -> None:
    keys = _collect_known_player_keys({"players": [{"player_key": "nba:1"}]}, {})
    assert keys == {"nba:1"}


def test_collect_known_player_keys_from_contest_players() -> None:
    keys = _collect_known_player_keys({}, {"players": [{"player_key": "nba:2"}]})
    assert keys == {"nba:2"}


def test_collect_known_player_keys_from_vip_lineups_players_live() -> None:
    contest = {"vip_lineups": [{"players_live": [{"player_key": "nba:3"}]}]}
    assert _collect_known_player_keys({}, contest) == {"nba:3"}


def test_collect_known_player_keys_from_vip_lineups_slots_fallback() -> None:
    contest = {"vip_lineups": [{"slots": [{"player_key": "nba:4"}]}]}
    assert _collect_known_player_keys({}, contest) == {"nba:4"}


def test_collect_known_player_keys_from_vip_lineups_lineup_fallback() -> None:
    contest = {"vip_lineups": [{"lineup": [{"player_key": "nba:5"}]}]}
    assert _collect_known_player_keys({}, contest) == {"nba:5"}


def test_collect_known_player_keys_from_vip_lineups_players_fallback() -> None:
    contest = {"vip_lineups": [{"players": [{"player_key": "nba:6"}]}]}
    assert _collect_known_player_keys({}, contest) == {"nba:6"}


def test_collect_known_player_keys_ignores_non_list_and_non_dict_rows() -> None:
    contest = {
        "players": "not-a-list",
        "vip_lineups": ["not-a-dict", {"players_live": "not-a-list", "slots": "also-not-a-list"}],
    }
    assert _collect_known_player_keys({"players": "not-a-list"}, contest) == set()


# ── _validate_train_cluster_references ───────────────────────────────────────


def test_validate_train_cluster_references_non_list_train_clusters_is_noop() -> None:
    assert _validate_train_cluster_references("nba", {"train_clusters": "not-a-list"}) == []


def test_validate_train_cluster_references_skips_non_dict_cluster() -> None:
    assert _validate_train_cluster_references("nba", {"train_clusters": ["not-a-dict"]}) == []


def test_validate_train_cluster_references_skips_non_list_sample_entries() -> None:
    contest = {"train_clusters": [{"entry_keys": ["e1"], "sample_entries": "not-a-list"}]}
    assert _validate_train_cluster_references("nba", contest) == []


def test_validate_train_cluster_references_skips_non_dict_sample() -> None:
    contest = {"train_clusters": [{"entry_keys": ["e1"], "sample_entries": ["not-a-dict"]}]}
    assert _validate_train_cluster_references("nba", contest) == []


def test_validate_train_cluster_references_skips_blank_sample_key() -> None:
    contest = {"train_clusters": [{"entry_keys": ["e1"], "sample_entries": [{"entry_key": ""}, {"entry_key": None}]}]}
    assert _validate_train_cluster_references("nba", contest) == []


def test_validate_train_cluster_references_accepts_matching_sample_key() -> None:
    contest = {"train_clusters": [{"entry_keys": ["e1"], "sample_entries": [{"entry_key": "e1"}]}]}
    assert _validate_train_cluster_references("nba", contest) == []
