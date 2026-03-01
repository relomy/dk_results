import json

import pytest

from dk_results.services.snapshot_v3.serialize import serialize_payload


def test_serialize_payload_requires_generated_at_in_deterministic_mode() -> None:
    with pytest.raises(ValueError, match="generated_at is required"):
        serialize_payload({"schema_version": 3}, generated_at=None, require_generated_at=True)


def test_serialize_payload_normalizes_generated_at_to_rfc3339_utc_seconds() -> None:
    text = serialize_payload(
        {"schema_version": 3, "sports": {}},
        generated_at="2026-02-25T10:11:12.987+00:00",
    )
    payload = json.loads(text)
    assert payload["generated_at"] == "2026-02-25T10:11:12Z"


def test_serialize_payload_is_stably_sorted() -> None:
    first = serialize_payload(
        {
            "sports": {"nba": {}, "golf": {}},
            "schema_version": 3,
            "snapshot_at": "2026-02-25T10:11:12Z",
            "generated_at": "2026-02-25T10:11:13Z",
        }
    )
    second = serialize_payload(
        {
            "generated_at": "2026-02-25T10:11:13Z",
            "snapshot_at": "2026-02-25T10:11:12Z",
            "sports": {"golf": {}, "nba": {}},
            "schema_version": 3,
        }
    )
    assert first == second
