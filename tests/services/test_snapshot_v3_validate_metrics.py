"""Metrics section of the snapshot validator: avg salary, non-cashing, threat field-remaining."""

import pytest

from dk_results.services.snapshot_v3.validate import _validate_section_rows, validate_v3_envelope
from tests.services.snapshot_v3_validate_builders import _valid_contest, _valid_envelope

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
