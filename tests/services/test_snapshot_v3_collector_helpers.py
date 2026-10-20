"""Extracted collector helpers: leaderboard payouts, VIP points, ownership total, truncation."""

from types import SimpleNamespace

from dk_results.services.snapshot_v3.collector import (
    _apply_truncation,
    _build_vip_points_by_entry,
    _compute_ownership_remaining_total,
    _fetch_leaderboard_payouts,
)
from tests.services.snapshot_v3_collector_fakes import _FakeDK


def test_fetch_leaderboard_payouts_maps_entries() -> None:
    dk = _FakeDK(leaderboard={"leaderBoard": [{"entryKey": "e1", "winningValue": "1.00"}]})
    assert _fetch_leaderboard_payouts(dk, 5) == {"e1": 100}


def test_fetch_leaderboard_payouts_reads_real_envelope_and_ignores_legacy_keys() -> None:
    real = {
        "leader": {"entryKey": "lead", "winningValue": 10},
        "leaderBoard": [
            {"entryKey": "5234772200", "winningValue": 10, "winnings": [{"value": 10, "description": "Cash"}]},
            {"entryKey": "5234800223", "winningValue": 4.28, "winnings": [{"value": 4.28, "description": "Cash"}]},
            {"entryKey": "5234800224", "winningValue": 0},
        ],
    }
    assert _fetch_leaderboard_payouts(_FakeDK(leaderboard=real), 5) == {
        "5234772200": 1000,
        "5234800223": 428,
        "5234800224": 0,
    }
    legacy = {"contestStandings": [{"entryKey": "e1", "winningValue": "1.00"}]}
    assert _fetch_leaderboard_payouts(_FakeDK(leaderboard=legacy), 5) == {}


def test_fetch_leaderboard_payouts_returns_empty_on_error() -> None:
    class _Boom:
        def get_leaderboard(self, _contest_id):
            raise RuntimeError("unavailable")

    assert _fetch_leaderboard_payouts(_Boom(), 5) == {}


def test_fetch_leaderboard_payouts_returns_empty_when_payload_not_dict() -> None:
    assert _fetch_leaderboard_payouts(_FakeDK(leaderboard=None), 5) == {}


def test_build_vip_points_prefers_rows_then_falls_back_to_vip_list() -> None:
    rows = [{"vip_entry_key": "e1", "pts": "12.5"}, {"entry_key": "e2", "pts": None}]
    vips = [SimpleNamespace(player_id="e1", pts="99"), SimpleNamespace(player_id="e3", pts="4.0")]

    # e1 comes from the lineup row (list value ignored), e2 is dropped (no points), e3 backfills.
    assert _build_vip_points_by_entry(rows, vips) == {"e1": 12.5, "e3": 4.0}


def test_compute_ownership_remaining_total_averages_non_null() -> None:
    rows = [
        {"ownership_remaining_total_pct": 10.0},
        {"ownership_remaining_total_pct": None},
        {"ownership_remaining_total_pct": 30.0},
    ]
    assert _compute_ownership_remaining_total(rows) == 20.0


def test_compute_ownership_remaining_total_none_when_all_null() -> None:
    assert _compute_ownership_remaining_total([{"ownership_remaining_total_pct": None}]) is None


def test_apply_truncation_caps_and_reports() -> None:
    rows = [{"i": i} for i in range(5)]
    standings, truncation = _apply_truncation(rows, 3)
    assert standings == rows[:3]
    assert truncation == {
        "applied": True,
        "limit": 3,
        "total_rows_before_truncation": 5,
        "total_rows_after_truncation": 3,
    }


def test_apply_truncation_noop_when_limit_zero() -> None:
    rows = [{"i": 0}]
    standings, truncation = _apply_truncation(rows, 0)
    assert standings == rows
    assert truncation == {
        "applied": False,
        "limit": None,
        "total_rows_before_truncation": 1,
        "total_rows_after_truncation": 1,
    }
