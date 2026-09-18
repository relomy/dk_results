import datetime

import pytest

from dk_results.services.snapshot_v3 import pipeline
from dk_results.services.snapshot_v3.normalize import (
    is_live_from_slot,
    normalize_name,
    slug,
    to_float,
    to_int,
    to_utc_iso,
)


def test_to_utc_iso_normalizes_naive_eastern_datetime() -> None:
    value = datetime.datetime(2026, 2, 14, 12, 30, 45)

    assert to_utc_iso(value) == "2026-02-14T17:30:45Z"


def test_to_utc_iso_normalizes_aware_utc_datetime() -> None:
    value = datetime.datetime(2026, 2, 14, 12, 30, 45, tzinfo=datetime.timezone.utc)

    assert to_utc_iso(value) == "2026-02-14T12:30:45Z"


def test_to_float_parses_currency_string() -> None:
    assert to_float("$10,300.50") == 10300.50


def test_to_int_rejects_non_integer_float() -> None:
    assert to_int(12.5) is None


def test_normalize_name_and_slug() -> None:
    assert normalize_name("  LeBron James  ") == "lebron james"
    assert slug("  LeBron James  ") == "lebron-james"


def test_is_live_from_slot_handles_numeric_and_text_status() -> None:
    assert is_live_from_slot({"time_remaining_minutes": 12}) is True
    assert is_live_from_slot({"timeStatus": "In Progress"}) is True
    assert is_live_from_slot({"timeStatus": "Final"}) is False


def test_is_live_from_slot_bool_is_live_short_circuits() -> None:
    assert is_live_from_slot({"is_live": True, "timeStatus": "Final"}) is True
    assert is_live_from_slot({"is_live": False, "timeStatus": "In Progress"}) is False


def test_is_live_from_slot_zero_minutes_is_not_live() -> None:
    assert is_live_from_slot({"timeRemaining": 0}) is False


def test_is_live_from_slot_skips_dash_placeholder_then_checks_next_candidate() -> None:
    assert is_live_from_slot({"timeStatus": "--", "game_status": "Q2"}) is True


def test_is_live_from_slot_colon_time_format_is_live() -> None:
    assert is_live_from_slot({"status": "2:15"}) is True


def test_is_live_from_slot_unknown_text_defaults_to_not_live() -> None:
    assert is_live_from_slot({"status": "scheduled"}) is False


def test_is_live_from_slot_empty_slot_defaults_to_not_live() -> None:
    assert is_live_from_slot({}) is False


def test_pipeline_exports_default_standings_limit() -> None:
    assert isinstance(pipeline.DEFAULT_STANDINGS_LIMIT, int)
    assert pipeline.DEFAULT_STANDINGS_LIMIT > 0


def test_pipeline_normalize_sport_name_accepts_known_sport() -> None:
    assert pipeline.normalize_sport_name("nba") == "NBA"


def test_pipeline_normalize_sport_name_rejects_unknown_sport() -> None:
    with pytest.raises(ValueError, match="Unsupported sport"):
        pipeline.normalize_sport_name("invalid-sport")
