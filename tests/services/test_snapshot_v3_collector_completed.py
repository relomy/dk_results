"""Completed contests: read like live ones, and carry completed_at only when stamped."""

from types import SimpleNamespace

import pytest

from dk_results.persistence.contestdatabase import ContestRow
from dk_results.services.snapshot_v3 import collector
from tests.services.snapshot_v3_collector_fakes import _FakeContestDB, _FakeDK, _field_user


def test_collect_reads_standings_and_draftables_for_a_completed_contest(monkeypatch, tmp_path) -> None:
    """A completed contest (the completion-window fallback) is read like a live one."""
    monkeypatch.setattr(collector, "SALARY_DIR", str(tmp_path))
    users = [_field_user(1, "e1", 0.10), _field_user(2, "e2", 0.20)]
    results = SimpleNamespace(
        vip_list=[],
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
    db = _FakeContestDB(by_id=row, state=("COMPLETED", 1))
    dk = _FakeDK(standings_rows=[["header"], ["row"]], leaderboard={})

    raw = collector._collect_source_snapshot(sport="NBA", contest_id=321, dk=dk, contest_db=db)

    assert raw["contest"]["state"] == "completed"
    assert [row["entry_key"] for row in raw["standings"]] == ["e1", "e2"]
    assert dk.draftables_requests == [8]
    assert dk.salary_path is not None


class _StandingsRecordingDK(_FakeDK):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.standings_requests: list[int] = []

    def download_contest_rows(self, dk_id, timeout=30, cookies_dump_file=None, contest_dir=None):
        self.standings_requests.append(dk_id)
        return super().download_contest_rows(dk_id, timeout, cookies_dump_file, contest_dir)


def _collect_contest_with_state(monkeypatch, tmp_path, *, state, completed_at):
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
    monkeypatch.setattr(collector, "load_vips", lambda: [])
    monkeypatch.setattr(collector, "parse_contest_standings", lambda *a, **k: results)
    monkeypatch.setattr(collector, "fetch_vip_lineups", lambda *a, **k: [])
    row = ContestRow(
        dk_id=321, name="Contest", draft_group=8, positions_paid=10, start_date="2026-01-04", entry_fee=5, entries=100
    )
    db = _FakeContestDB(by_id=row, state=state, completed_at=completed_at)
    dk = _StandingsRecordingDK(standings_rows=[["header"], ["row"]], leaderboard={})
    raw = collector._collect_source_snapshot(sport="NBA", contest_id=321, dk=dk, contest_db=db)
    return raw, dk


def test_completed_contest_carries_its_stored_completed_at_and_still_reads_standings(monkeypatch, tmp_path) -> None:
    raw, dk = _collect_contest_with_state(
        monkeypatch, tmp_path, state=("COMPLETED", 1), completed_at="2026-10-10T12:00:00Z"
    )

    assert raw["contest"]["state"] == "completed"
    assert raw["contest"]["completed_at"] == "2026-10-10T12:00:00Z"
    assert dk.standings_requests == [321]


@pytest.mark.parametrize(
    ("state", "completed_at"),
    [
        (("LIVE", 0), None),
        (("LIVE", 0), "2026-10-10T12:00:00Z"),  # a stray stamp never leaks onto a non-completed contest
        (("CANCELLED", 1), None),
        (("CANCELLED", 1), "2026-10-10T12:00:00Z"),
        (("COMPLETED", 1), None),  # completed before the stamp existed
    ],
)
def test_completed_at_key_is_absent_unless_the_contest_is_completed_and_stamped(
    monkeypatch, tmp_path, state, completed_at
) -> None:
    raw, _dk = _collect_contest_with_state(monkeypatch, tmp_path, state=state, completed_at=completed_at)

    assert "completed_at" not in raw["contest"]
