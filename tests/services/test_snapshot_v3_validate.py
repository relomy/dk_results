from copy import deepcopy

import pytest

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


def test_validate_v3_envelope_accepts_a_completed_at_timestamp() -> None:
    payload = _valid_envelope()
    payload["sports"]["nba"]["contests"][0]["completed_at"] = "2026-02-25T09:30:00Z"
    assert validate_v3_envelope(payload) == []


@pytest.mark.parametrize("bad_value", ["not-a-timestamp", "", 12, None])
def test_validate_v3_envelope_rejects_a_malformed_or_null_completed_at(bad_value) -> None:
    payload = _valid_envelope()
    payload["sports"]["nba"]["contests"][0]["completed_at"] = bad_value
    violations = validate_v3_envelope(payload)
    assert any("contests[0].completed_at" in violation for violation in violations)


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


# ── avg salary remaining and non-cashing ─────────────────────────────────────

LIVE_AVG = "sports.nba.contests[0].live_metrics.avg_salary_per_player_remaining"
NON_CASHING = "sports.nba.contests[0].metrics.non_cashing"


def _valid_non_cashing() -> dict:
    return {
        "users_not_cashing": 40,
        "avg_pmr_remaining": 123.46,
        "top_remaining_players": [{"player_name": "A", "ownership_remaining_pct": 62.5}],
    }


def test_validate_section_rows_accepts_valid_avg_salary_and_non_cashing() -> None:
    contest = _valid_contest()
    contest["live_metrics"] = {"avg_salary_per_player_remaining": 6543.22}
    contest["metrics"]["non_cashing"] = _valid_non_cashing()
    assert _validate_section_rows("nba", contest) == []


def test_validate_section_rows_accepts_non_cashing_without_top_remaining_players() -> None:
    contest = _valid_contest()
    contest["metrics"]["non_cashing"] = {"users_not_cashing": 3, "avg_pmr_remaining": 0.0}
    assert _validate_section_rows("nba", contest) == []


@pytest.mark.parametrize("bad", ["6000", None, True, float("nan"), float("inf"), -1.0])
def test_validate_section_rows_rejects_malformed_avg_salary(bad) -> None:
    contest = _valid_contest()
    contest["live_metrics"] = {"avg_salary_per_player_remaining": bad}
    assert f"{LIVE_AVG} has invalid type" in _validate_section_rows("nba", contest)


def test_validate_section_rows_rejects_non_dict_non_cashing() -> None:
    contest = _valid_contest()
    contest["metrics"]["non_cashing"] = "bad"
    assert f"{NON_CASHING} has invalid type" in _validate_section_rows("nba", contest)


@pytest.mark.parametrize(
    ("field", "bad"),
    [
        ("users_not_cashing", "40"),
        ("users_not_cashing", 4.5),
        ("users_not_cashing", True),
        ("users_not_cashing", None),
        ("avg_pmr_remaining", "1.0"),
        ("avg_pmr_remaining", None),
        ("avg_pmr_remaining", float("nan")),
        ("top_remaining_players", "bad"),
        ("top_remaining_players", None),
    ],
)
def test_validate_v3_envelope_rejects_malformed_non_cashing_fields(field, bad) -> None:
    envelope = _valid_envelope()
    non_cashing = _valid_non_cashing()
    non_cashing[field] = bad
    envelope["sports"]["nba"]["contests"][0]["metrics"]["non_cashing"] = non_cashing

    assert f"{NON_CASHING}.{field} has invalid type" in validate_v3_envelope(envelope)


@pytest.mark.parametrize("missing", ["users_not_cashing", "avg_pmr_remaining"])
def test_validate_v3_envelope_requires_core_non_cashing_fields(missing) -> None:
    envelope = _valid_envelope()
    non_cashing = _valid_non_cashing()
    del non_cashing[missing]
    envelope["sports"]["nba"]["contests"][0]["metrics"]["non_cashing"] = non_cashing

    assert f"{NON_CASHING}.{missing} is required" in validate_v3_envelope(envelope)


@pytest.mark.parametrize(
    "row",
    [
        "bad",
        {"ownership_remaining_pct": 5.0},
        {"player_name": "", "ownership_remaining_pct": 5.0},
        {"player_name": "A"},
        {"player_name": "A", "ownership_remaining_pct": "5"},
    ],
)
def test_validate_v3_envelope_rejects_malformed_top_remaining_player_rows(row) -> None:
    envelope = _valid_envelope()
    non_cashing = _valid_non_cashing()
    non_cashing["top_remaining_players"] = [row]
    envelope["sports"]["nba"]["contests"][0]["metrics"]["non_cashing"] = non_cashing

    violations = validate_v3_envelope(envelope)

    assert any(message.startswith(f"{NON_CASHING}.top_remaining_players[0]") for message in violations)


# ── threat field-remaining group and leverage ────────────────────────────────

THREAT = "sports.nba.contests[0].metrics.threat"
FIELD_REMAINING_KEYS = (
    "leverage_semantics",
    "field_remaining_scope",
    "field_remaining_source",
    "field_remaining_pct",
    "field_remaining_is_partial",
)


def _threat_with_field_remaining() -> dict:
    return {
        "leverage_semantics": "positive=unique",
        "field_remaining_scope": "contest_field",
        "field_remaining_source": "contest_standings_mean",
        "field_remaining_pct": 41.24,
        "field_remaining_is_partial": False,
    }


def _envelope_with_threat(threat: dict) -> dict:
    envelope = _valid_envelope()
    envelope["sports"]["nba"]["contests"][0]["metrics"]["threat"] = threat
    return envelope


def test_validate_v3_envelope_accepts_complete_field_remaining_group() -> None:
    assert validate_v3_envelope(_envelope_with_threat(_threat_with_field_remaining())) == []


@pytest.mark.parametrize("missing", FIELD_REMAINING_KEYS)
def test_validate_v3_envelope_requires_every_field_remaining_key_when_any_is_present(missing) -> None:
    threat = _threat_with_field_remaining()
    del threat[missing]

    assert f"{THREAT}.{missing} is required" in validate_v3_envelope(_envelope_with_threat(threat))


@pytest.mark.parametrize("present", FIELD_REMAINING_KEYS)
def test_validate_v3_envelope_rejects_lone_field_remaining_key(present) -> None:
    threat = {present: _threat_with_field_remaining()[present]}

    violations = validate_v3_envelope(_envelope_with_threat(threat))

    assert {f"{THREAT}.{key} is required" for key in FIELD_REMAINING_KEYS if key != present} <= set(violations)


@pytest.mark.parametrize(
    ("field", "bad", "message"),
    [
        ("leverage_semantics", "negative=unique", "has invalid value"),
        ("field_remaining_scope", "watchlist", "has invalid value"),
        ("field_remaining_source", "other", "has invalid value"),
        ("field_remaining_pct", "41", "has invalid type"),
        ("field_remaining_is_partial", "no", "has invalid type"),
    ],
)
def test_validate_v3_envelope_checks_each_field_remaining_key_without_the_pct(field, bad, message) -> None:
    threat = _threat_with_field_remaining()
    threat[field] = bad

    assert f"{THREAT}.{field} {message}" in validate_v3_envelope(_envelope_with_threat(threat))


def test_validate_v3_envelope_rejects_leverage_without_field_remaining_pct() -> None:
    threat = {
        "vip_vs_field_leverage": [
            {
                "vip_entry_key": "v1",
                "entry_key": "e1",
                "display_name": "Alice",
                "vip_remaining_pct": 25.0,
                "field_remaining_pct": 40.0,
                "uniqueness_delta_pct": 15.0,
            }
        ]
    }

    violations = validate_v3_envelope(_envelope_with_threat(threat))

    assert f"{THREAT}.vip_vs_field_leverage requires field_remaining_pct" in violations


def test_validate_v3_envelope_rejects_more_than_ten_top_remaining_players() -> None:
    envelope = _valid_envelope()
    non_cashing = _valid_non_cashing()
    non_cashing["top_remaining_players"] = [
        {"player_name": f"P{index}", "ownership_remaining_pct": 5.0} for index in range(11)
    ]
    envelope["sports"]["nba"]["contests"][0]["metrics"]["non_cashing"] = non_cashing

    assert f"{NON_CASHING}.top_remaining_players has more than 10 rows" in validate_v3_envelope(envelope)


def test_validate_v3_envelope_accepts_ten_top_remaining_players() -> None:
    envelope = _valid_envelope()
    non_cashing = _valid_non_cashing()
    non_cashing["top_remaining_players"] = [
        {"player_name": f"P{index}", "ownership_remaining_pct": 5.0} for index in range(10)
    ]
    envelope["sports"]["nba"]["contests"][0]["metrics"]["non_cashing"] = non_cashing

    assert validate_v3_envelope(envelope) == []


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


def test_collect_known_player_keys_ignores_locked_vip_slots() -> None:
    contest = {"vip_lineups": [{"players_live": [{"player_key": "nba:hidden", "is_locked": True}]}]}
    assert _collect_known_player_keys({}, contest) == set()


@pytest.mark.parametrize(
    ("slot_row", "expected"),
    [
        ({"player_name": "A", "player_key": "nba:1"}, ".slot is required"),
        ({"slot": 3, "player_name": "A"}, ".slot has invalid type"),
        ({"slot": "UTIL", "player_name": "A", "is_locked": "yes"}, ".is_locked has invalid type"),
        (
            {"slot": "UTIL", "player_name": "LOCKED 🔒", "is_locked": True, "player_key": "nba:1"},
            ".player_key is forbidden for locked slot",
        ),
        (
            {"slot": "UTIL", "player_name": "LOCKED 🔒", "is_locked": True, "salary": 5000},
            ".salary is forbidden for locked slot",
        ),
        (
            {"slot": "UTIL", "player_name": "LOCKED 🔒", "is_locked": True, "is_live": False},
            ".is_live is forbidden for locked slot",
        ),
        ({"slot": "DST", "player_name": "Rams "}, ".player_name must not have leading or trailing whitespace"),
        ({"slot": "DST", "player_name": " Rams"}, ".player_name must not have leading or trailing whitespace"),
    ],
)
def test_validate_v3_envelope_checks_vip_slot_contract(slot_row: dict, expected: str) -> None:
    payload = _valid_envelope()
    payload["sports"]["nba"]["contests"][0]["vip_lineups"] = [{"players_live": [slot_row]}]

    violations = validate_v3_envelope(payload)

    assert any("vip_lineups[0].players_live[0]" in violation and expected in violation for violation in violations)


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


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("rank", "879"),
        ("rank", 879.5),
        ("rank", True),
        ("points", "28.64"),
        ("points", float("nan")),
        ("pmr", "390"),
        ("pmr", None),
    ],
)
def test_validate_v3_envelope_rejects_non_numeric_vip_figures(field: str, value) -> None:
    payload = _valid_envelope()
    payload["sports"]["nba"]["contests"][0]["vip_lineups"] = [{field: value}]

    assert f"sports.nba.contests[0].vip_lineups[0].{field} has invalid type" in validate_v3_envelope(payload)


def test_validate_v3_envelope_accepts_numeric_vip_figures() -> None:
    payload = _valid_envelope()
    payload["sports"]["nba"]["contests"][0]["vip_lineups"] = [{"rank": 879, "points": 28.64, "pmr": 390.0}]

    assert validate_v3_envelope(payload) == []
