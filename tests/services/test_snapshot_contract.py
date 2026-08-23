from dk_results.services.snapshot_contract import (
    DashboardEnvelope,
    collected_snapshot_from_mapping,
    validate_v3_envelope,
)


def _envelope() -> dict:
    return DashboardEnvelope(
        snapshot_at="2026-08-23T12:00:00Z",
        generated_at="2026-08-23T12:00:00Z",
        sports={
            "nba": {
                "contests": [{"contest_key": "nba:1", "sport": "nba"}],
            }
        },
    ).to_dict()


def test_schema_three_envelope_is_deterministic_and_valid() -> None:
    payload = _envelope()
    assert payload["schema_version"] == 3
    assert validate_v3_envelope(payload) == []


def test_collected_snapshot_conversion_exposes_typed_stage_sections() -> None:
    collected = collected_snapshot_from_mapping(
        {"sport": "NBA", "contest": {"contest_id": "1"}, "standings": [{"entry_key": "e1"}]}
    )
    assert collected.sport == "NBA"
    assert collected.standings == ({"entry_key": "e1"},)


def test_validation_rejects_cardinality_and_cross_source_collisions() -> None:
    payload = _envelope()
    payload["sports"]["nba"]["contests"].append({"contest_key": "nba:2", "sport": "nba"})
    payload["sports"]["mlb"] = {"contests": [{"contest_key": "nba:1", "sport": "mlb"}]}
    violations = validate_v3_envelope(payload)
    assert "sports.nba.contests must contain exactly one contest" in violations
    assert "contest_key collision: nba:1" in violations
    assert "sports.mlb.contests[0].contest_key must match sport key" in violations


def test_validation_rejects_missing_contest_key() -> None:
    payload = _envelope()
    payload["sports"]["nba"]["contests"][0].pop("contest_key")
    assert "sports.nba.contests[0].contest_key is required" in validate_v3_envelope(payload)
