"""Field remaining over the full standings, from stubbed standings results."""

from types import SimpleNamespace

import pytest

from dk_results.persistence.contestdatabase import ContestRow
from dk_results.services.snapshot_v3 import collector
from tests.services.snapshot_v3_collector_fakes import _FakeContestDB, _FakeDK, _field_user


def _collect_with_users(monkeypatch, tmp_path, users, *, standings_limit, vip_list=()):
    monkeypatch.setattr(collector, "SALARY_DIR", str(tmp_path))
    results = SimpleNamespace(
        vip_list=list(vip_list),
        players={},
        users=users,
        non_cashing_users=0,
        non_cashing_avg_pmr=None,
        min_rank=0,
        min_cash_pts=0.0,
        non_cashing_players={},
    )
    monkeypatch.setattr(collector, "load_vips", lambda: [])
    monkeypatch.setattr(collector, "parse_contest_standings", lambda *a, **k: results)
    monkeypatch.setattr(collector, "fetch_vip_lineups", lambda *a, **k: [])
    row = ContestRow(
        dk_id=321, name="C", draft_group=8, positions_paid=10, start_date="2026-01-04", entry_fee=5, entries=100
    )
    dk = _FakeDK(standings_rows=[["header"], ["row"]], leaderboard={})
    return collector._collect_source_snapshot(
        sport="NBA", contest_id=321, standings_limit=standings_limit, dk=dk, contest_db=_FakeContestDB(by_id=row)
    )


def test_field_remaining_is_the_mean_over_full_standings_before_truncation(monkeypatch, tmp_path) -> None:
    users = [_field_user(1, "e1", 0.10), _field_user(2, "e2", 0.20), _field_user(3, "e3", 0.60)]

    raw = _collect_with_users(monkeypatch, tmp_path, users, standings_limit=1)

    assert len(raw["standings"]) == 1  # truncated
    assert raw["ownership"]["field_remaining_pct"] == pytest.approx(30.0)  # not 10.0 from the kept row
    assert raw["ownership"]["field_remaining_is_partial"] is False


def test_field_remaining_is_partial_exactly_when_a_row_has_no_resolvable_lineup(monkeypatch, tmp_path) -> None:
    users = [_field_user(1, "e1", 0.10), _field_user(2, "e2", None), _field_user(3, "e3", 0.30)]

    raw = _collect_with_users(monkeypatch, tmp_path, users, standings_limit=500)

    assert raw["ownership"]["field_remaining_pct"] == pytest.approx(20.0)
    assert raw["ownership"]["field_remaining_is_partial"] is True


def test_field_remaining_is_none_when_no_row_has_a_lineup(monkeypatch, tmp_path) -> None:
    raw = _collect_with_users(monkeypatch, tmp_path, [_field_user(1, "e1", None)], standings_limit=500)

    assert raw["ownership"]["field_remaining_pct"] is None


def test_vip_remaining_by_entry_key_covers_vips_ranked_below_the_standings_limit(monkeypatch, tmp_path) -> None:
    users = [_field_user(1, "e1", 0.10), _field_user(2, "e2", 0.20), _field_user(3, "e3", 0.60)]
    users[2].name = "vip-user"
    results_vips = [SimpleNamespace(name="vip-user", player_id="e3", pts="5", pmr="0", rank="3")]

    raw = _collect_with_users(monkeypatch, tmp_path, users, standings_limit=1, vip_list=results_vips)

    assert [row["entry_key"] for row in raw["standings"]] == ["e1"]  # the VIP's row was truncated away
    assert raw["ownership"]["vip_remaining_by_entry_key"] == {"e3": pytest.approx(60.0)}


@pytest.mark.parametrize("game_info", ["Delayed", "Suspended"])
def test_delayed_and_suspended_players_count_toward_collector_remaining_metrics(
    monkeypatch, tmp_path, game_info
) -> None:
    users = [
        _field_user(1, "e1", 0.10, game_info="Final", salary=5000),
        _field_user(2, "e2", 0.30, game_info=game_info, salary=7000),
    ]

    raw = _collect_with_users(monkeypatch, tmp_path, users, standings_limit=500)

    assert raw["ownership"]["field_remaining_pct"] == pytest.approx(15.0)  # (0 + 30) / 2
    assert raw["ownership"]["avg_salary_per_player_remaining"] == pytest.approx(7000.0)


@pytest.mark.parametrize("game_info", ["Postponed", "Cancelled"])
def test_postponed_and_cancelled_players_do_not_count_toward_collector_remaining_metrics(
    monkeypatch, tmp_path, game_info
) -> None:
    users = [
        _field_user(1, "e1", 0.10, game_info=game_info, salary=5000),
        _field_user(2, "e2", 0.30, game_info="Live", salary=7000),
    ]

    raw = _collect_with_users(monkeypatch, tmp_path, users, standings_limit=500)

    assert raw["ownership"]["field_remaining_pct"] == pytest.approx(15.0)  # (0 + 30) / 2
    assert raw["ownership"]["avg_salary_per_player_remaining"] == pytest.approx(7000.0)
