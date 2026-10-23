"""The collector orchestrator through its injectable seam (fake DraftKings and contest DB)."""

import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from dk_results.persistence.contestdatabase import ContestRow
from dk_results.services.snapshot_v3 import collector
from dk_results.services.snapshot_v3.collector import collect_snapshot
from tests.services.snapshot_v3_collector_fakes import _FakeContestDB, _FakeDK


def test_collect_source_snapshot_runs_end_to_end_through_injected_fakes(monkeypatch, tmp_path) -> None:
    sport_cls = collector._sport_choices()["NBA"]
    monkeypatch.setattr(collector, "SALARY_DIR", str(tmp_path))

    results = SimpleNamespace(
        vip_list=[],
        players={},
        users=[],
        non_cashing_users=0,
        non_cashing_avg_pmr=None,
        min_rank=0,
        min_cash_pts=0.0,
        non_cashing_players={},
    )
    # Stub the external-data boundaries; the pure section builders and the new
    # helpers all run for real against the results object.
    monkeypatch.setattr(collector, "load_vips", lambda: [])
    monkeypatch.setattr(collector, "parse_contest_standings", lambda *a, **k: results)
    monkeypatch.setattr(collector, "fetch_vip_lineups", lambda *a, **k: [])

    row = ContestRow(
        dk_id=321,
        name="Contest",
        draft_group=8,
        positions_paid=10,
        start_date="2026-01-04",
        entry_fee=5,
        entries=100,
    )
    db = _FakeContestDB(by_id=row)
    dk = _FakeDK(standings_rows=[["header"], ["row"]], leaderboard={})

    raw = collector._collect_source_snapshot(sport="NBA", contest_id=321, dk=dk, contest_db=db)

    assert raw["sport"] == sport_cls.name
    assert raw["contest"]["contest_id"] == 321
    assert raw["selection"]["selected_contest_id"] == 321
    assert raw["standings"] == []
    assert raw["truncation"]["applied"] is False
    assert dk.salary_path is not None  # salary download was wired
    assert db.closed is False  # an injected DB is never closed by the collector


def test_collect_source_snapshot_raises_when_standings_unavailable(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(collector, "SALARY_DIR", str(tmp_path))
    monkeypatch.setattr(collector, "load_vips", lambda: [])

    row = ContestRow(
        dk_id=321,
        name="Contest",
        draft_group=8,
        positions_paid=10,
        start_date="2026-01-04",
        entry_fee=5,
        entries=100,
    )
    db = _FakeContestDB(by_id=row)
    dk = _FakeDK(standings_rows=[])  # empty -> unavailable

    try:
        collector._collect_source_snapshot(sport="NBA", contest_id=321, dk=dk, contest_db=db)
    except RuntimeError as exc:
        assert "standings unavailable" in str(exc).lower()
    else:
        raise AssertionError("expected RuntimeError for unavailable standings")


def test_collect_source_snapshot_no_draft_group_skips_salary_and_vip_fetch(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(collector, "SALARY_DIR", str(tmp_path))
    monkeypatch.setattr(collector, "load_vips", lambda: [])

    results = SimpleNamespace(
        vip_list=[],
        players={},
        users=[],
        non_cashing_users=0,
        non_cashing_avg_pmr=None,
        min_rank=0,
        min_cash_pts=0.0,
        non_cashing_players={},
    )
    monkeypatch.setattr(collector, "parse_contest_standings", lambda *a, **k: results)

    def _boom_fetch(*_args, **_kwargs):
        raise AssertionError("fetch_vip_lineups must not be called without a draft group")

    monkeypatch.setattr(collector, "fetch_vip_lineups", _boom_fetch)

    row = ContestRow(
        dk_id=321,
        name="Contest",
        draft_group=None,
        positions_paid=10,
        start_date="2026-01-04",
        entry_fee=5,
        entries=100,
    )
    db = _FakeContestDB(by_id=row)
    dk = _FakeDK(standings_rows=[["header"], ["row"]], leaderboard={})

    now_et = datetime.datetime.now(ZoneInfo("America/New_York"))
    salary_path = tmp_path / f"DKSalaries_NBA_{now_et:%A}.csv"
    salary_path.write_text(
        "Position,Name+ID,Name,ID,Roster Position,Salary,Game Info,TeamAbbrev,AvgPointsPerGame\n",
        encoding="utf-8",
    )

    raw = collector._collect_source_snapshot(sport="NBA", contest_id=321, dk=dk, contest_db=db)

    assert raw["contest"]["draft_group"] is None
    assert raw["vip_lineups"] == []
    assert dk.salary_path is None  # download_salary_csv was never called
    assert dk.draftables_requests == []  # no draft group, no draftables read


def test_collect_snapshot_called_directly_returns_collected_snapshot(monkeypatch) -> None:
    raw = {
        "sport": "nba",
        "contest": {"contest_id": 321},
        "selection": {"selected_contest_id": 321, "reason": {"mode": "explicit_id"}},
        "candidates": [],
        "cash_line": {},
        "vip_lineups": [],
        "players": [],
        "ownership": {},
        "standings": [],
        "train_clusters": [],
        "truncation": {},
    }
    monkeypatch.setattr(collector, "_collect_source_snapshot", lambda **_kwargs: raw)

    snapshot = collect_snapshot(sport="nba", contest_id=321)

    assert snapshot.bundle["sport"] == "nba"
    assert snapshot.bundle["selected_contest_id"] == 321
    assert snapshot.bundle["selection_reason"] == {"mode": "explicit_id"}
    assert snapshot.bundle["standings"] == []
