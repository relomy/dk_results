"""Contest selection: explicit id and primary live, against the fake contest DB."""

from dk_results.persistence.contestdatabase import ContestRow
from dk_results.services.snapshot_v3 import collector
from dk_results.services.snapshot_v3.collector import _select_contest
from tests.services.snapshot_v3_collector_fakes import _FakeContestDB, _FakeDK


def test_select_contest_explicit_id_uses_db_row_and_merges_state_and_contract() -> None:
    sport_cls = collector._sport_choices()["NBA"]
    row = ContestRow(
        dk_id=123,
        name="C",
        draft_group=7,
        positions_paid=10,
        start_date="2026-01-01",
        entry_fee=5,
        entries=100,
    )
    db = _FakeContestDB(
        by_id=row,
        candidates=[(1, "n", 5, "d", 9, 0)],
        state=("live", 0),
        contract=(500, 200, 3, 150),
    )

    resolved = _select_contest(sport_cls=sport_cls, contest_db=db, contest_id=123, dk=_FakeDK())

    assert resolved.mode == "explicit_id"
    assert resolved.dk_id == 123
    assert resolved.contest_state == "live"
    assert resolved.prize_pool == 500
    assert resolved.max_entries == 200  # contract capacity overrides row entries
    assert resolved.max_entries_per_user == 3
    assert resolved.candidate_rows == [(1, "n", 5, "d", 9, 0)]


def test_select_contest_explicit_id_falls_back_to_dk_detail_when_db_misses() -> None:
    sport_cls = collector._sport_choices()["NBA"]
    detail = {
        "contestDetail": {
            "name": "FromDetail",
            "draftGroupId": 9,
            "contestStartTime": "2026-01-02",
            "entryFee": 10,
            "maximumEntries": 50,
            "payoutSummary": [{"maxPosition": 5}],
        }
    }
    db = _FakeContestDB(by_id=None)

    resolved = _select_contest(sport_cls=sport_cls, contest_db=db, contest_id=999, dk=_FakeDK(detail=detail))

    assert resolved.dk_id == 999
    assert resolved.contest_name == "FromDetail"
    assert resolved.draft_group == 9
    assert resolved.positions_paid == 5


def test_select_contest_primary_live_selects_live_contest() -> None:
    sport_cls = collector._sport_choices()["NBA"]
    row = ContestRow(
        dk_id=55,
        name="Live",
        draft_group=3,
        positions_paid=20,
        start_date="2026-01-03",
        entry_fee=5,
        entries=200,
    )
    db = _FakeContestDB(by_id=row, live=(55,))

    resolved = _select_contest(sport_cls=sport_cls, contest_db=db, contest_id=None, dk=_FakeDK())

    assert resolved.mode == "primary_live"
    assert resolved.dk_id == 55


def test_select_contest_raises_without_db_for_primary_live() -> None:
    sport_cls = collector._sport_choices()["NBA"]
    try:
        _select_contest(sport_cls=sport_cls, contest_db=None, contest_id=None, dk=_FakeDK())
    except RuntimeError as exc:
        assert "unavailable" in str(exc).lower()
    else:
        raise AssertionError("expected RuntimeError")


def test_select_contest_raises_when_no_contest_found() -> None:
    sport_cls = collector._sport_choices()["NBA"]
    db = _FakeContestDB(by_id=None, live=None)
    try:
        _select_contest(sport_cls=sport_cls, contest_db=db, contest_id=None, dk=_FakeDK())
    except RuntimeError as exc:
        assert "no contest found" in str(exc).lower()
    else:
        raise AssertionError("expected RuntimeError")
