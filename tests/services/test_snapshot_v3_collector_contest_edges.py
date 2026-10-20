"""Contest edges through the collector seam: candidates, state, DK detail fallback, payouts, own DB."""

from types import SimpleNamespace

import pytest

from dk_results.persistence.contestdatabase import ContestRow
from dk_results.services.snapshot_v3 import collector
from tests.services.snapshot_v3_collector_fakes import _FakeContestDB, _FakeDK

_ROW = ContestRow(
    dk_id=321, name="C", draft_group=8, positions_paid=10, start_date="2026-01-04", entry_fee=5, entries=100
)


def _collect(monkeypatch, tmp_path, *, contest_db, dk=None, contest_id=321):
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
    dk = dk or _FakeDK(standings_rows=[["header"], ["row"]], leaderboard={})
    return collector._collect_source_snapshot(sport="NBA", contest_id=contest_id, dk=dk, contest_db=contest_db)


def test_primary_live_selection_summarizes_the_top_candidates_in_priority_order(monkeypatch, tmp_path) -> None:
    candidates = [
        (6, "fee-low", 1, "2026-01-04T12:00:00", 900, 1),
        (5, "prio-0-small", 5, "2026-01-04T12:00:00", 10, 0),
        (4, "prio-0-big-fee", 20, "2026-01-04T12:00:00", 10, 0),
        (3, "prio-0-many", 5, "2026-01-04T12:00:00", 500, 0),
        (2, "tie-a", 5, None, 10, 0),
        (7, "fee-high", 50, "2026-01-04T12:00:00", 1, 1),
    ]
    db = _FakeContestDB(by_id=_ROW, live=(321,), candidates=candidates)

    raw = _collect(monkeypatch, tmp_path, contest_db=db, contest_id=None)

    assert [c["name"] for c in raw["candidates"]] == [
        "prio-0-big-fee",
        "prio-0-many",
        "tie-a",
        "prio-0-small",
        "fee-high",
    ]
    assert raw["candidates"][0] == {
        "contest_id": "4",
        "name": "prio-0-big-fee",
        "entry_fee": 20,
        "entries": 10,
        "start_time_utc": "2026-01-04T17:00:00Z",
        "selection_priority": 0,
    }
    reason = raw["selection"]["reason"]
    assert reason["mode"] == "primary_live"
    assert reason["criteria"]["sport"] == "NBA"
    assert reason["criteria"]["keyword"] == collector._sport_choices()["NBA"].keyword
    assert reason["selected_from_candidate_count"] == 6


def test_explicit_id_selection_reason_names_only_the_contest_id(monkeypatch, tmp_path) -> None:
    raw = _collect(monkeypatch, tmp_path, contest_db=_FakeContestDB(by_id=_ROW))

    assert raw["selection"]["reason"]["mode"] == "explicit_id"
    assert raw["selection"]["reason"]["criteria"] == {"contest_id": "321"}
    assert raw["candidates"] == []


@pytest.mark.parametrize(
    ("db_state", "expected"),
    [
        (("In Progress", 0), "live"),
        (("started", 0), "live"),
        (("Final", 0), "completed"),
        (("anything", "true"), "completed"),
        (("Canceled", 0), "cancelled"),
        (("open", 0), "upcoming"),
        (("Scheduled", 0), "upcoming"),
        (("mystery", 0), None),
        ((None, 0), None),
        (("  ", None), None),
    ],
)
def test_contest_state_is_normalized_from_the_db_state_row(monkeypatch, tmp_path, db_state, expected) -> None:
    raw = _collect(monkeypatch, tmp_path, contest_db=_FakeContestDB(by_id=_ROW, state=db_state))

    assert raw["contest"]["state"] == expected


def test_blank_contract_metadata_keeps_the_row_capacity_and_per_user_limit(monkeypatch, tmp_path) -> None:
    row = ContestRow(
        dk_id=321,
        name="C",
        draft_group=8,
        positions_paid=10,
        start_date="2026-01-04",
        entry_fee=5,
        entries=100,
        max_entries_per_user=150,
    )
    db = _FakeContestDB(by_id=row, contract=(None, "", None, 40))

    raw = _collect(monkeypatch, tmp_path, contest_db=db)

    assert raw["contest"]["max_entries"] == 100
    assert raw["contest"]["entries"] == 100
    assert raw["contest"]["max_entries_per_user"] == 150
    assert raw["contest"]["prize_pool"] is None


def test_explicit_id_without_a_db_reads_contest_detail_and_its_fallback_keys(monkeypatch, tmp_path) -> None:
    detail = {
        "contestDetail": {
            "name": "FromDetail",
            "draftGroupId": 9,
            "contestStartTime": "2026-01-02T20:00:00Z",
            "entryFee": 10,
            "maximumEntries": 50,
            "payoutSummary": [],
            "totalPrizePool": "",
            "totalPayouts": 1000,
            "maxEntryCount": 3,
            "contestStatus": "Live",
        }
    }
    dk = _FakeDK(detail=detail, standings_rows=[["header"], ["row"]], leaderboard={})

    raw = _collect(monkeypatch, tmp_path, contest_db=None, dk=dk, contest_id=999)

    fields = ("contest_id", "name", "draft_group", "start_time_utc", "positions_paid", "prize_pool")
    assert {key: raw["contest"][key] for key in fields} == {
        "contest_id": 999,
        "name": "FromDetail",
        "draft_group": 9,
        "start_time_utc": "2026-01-02T20:00:00Z",
        "positions_paid": None,  # empty payout summary
        "prize_pool": 1000,  # first non-blank prize key
    }
    limits = ("max_entries", "max_entries_per_user", "state")
    assert {key: raw["contest"][key] for key in limits} == {
        "max_entries": 50,
        "max_entries_per_user": 3,
        "state": "live",
    }
    assert raw["candidates"] == []


def test_contest_detail_with_no_prize_or_per_user_keys_leaves_them_none(monkeypatch, tmp_path) -> None:
    dk = _FakeDK(
        detail={"contestDetail": {"name": "Bare", "draftGroupId": 9}},
        standings_rows=[["header"], ["row"]],
        leaderboard={},
    )

    raw = _collect(monkeypatch, tmp_path, contest_db=None, dk=dk, contest_id=999)

    assert raw["contest"]["name"] == "Bare"
    assert raw["contest"]["prize_pool"] is None
    assert raw["contest"]["max_entries_per_user"] is None
    assert raw["contest"]["state"] is None


def test_leaderboard_payouts_skip_rows_without_a_dict_entry_key_or_cash() -> None:
    leaderboard = {
        "leaderBoard": [
            "not-a-row",
            {"winningValue": "5.00"},
            {"entryKey": "", "winningValue": "5.00"},
            {"entryKey": "no-cash"},
            {"entryId": "e2", "winningValue": "2.50"},
            {"entry_id": 7, "winningValue": "1.00"},
        ]
    }

    assert collector._fetch_leaderboard_payouts(_FakeDK(leaderboard=leaderboard), 5) == {"e2": 250, "7": 100}


@pytest.mark.parametrize("payload", [{"leaderBoard": "not-a-list"}, {}, ["not", "a", "dict"]])
def test_leaderboard_payouts_are_empty_for_a_malformed_payload(payload) -> None:
    dk = _FakeDK()
    dk._leaderboard = payload

    assert collector._fetch_leaderboard_payouts(dk, 5) == {}


def test_collector_opens_and_closes_its_own_db_from_the_state_path(monkeypatch, tmp_path) -> None:
    opened: list[str] = []
    db = _FakeContestDB(by_id=_ROW)

    def _open(path):
        opened.append(path)
        return db

    monkeypatch.setattr(collector, "state", SimpleNamespace(contests_db_path=lambda: tmp_path / "contests.db"))
    monkeypatch.setattr(collector, "ContestDatabase", _open)

    raw = _collect(monkeypatch, tmp_path, contest_db=None)

    assert opened == [str(tmp_path / "contests.db")]
    assert raw["contest"]["contest_id"] == 321
    assert db.closed is True  # a DB the collector opened itself is closed


def test_collector_runs_without_a_db_when_opening_it_fails(monkeypatch, tmp_path) -> None:
    def _unavailable():
        raise OSError("no state dir")

    monkeypatch.setattr(collector, "state", SimpleNamespace(contests_db_path=_unavailable))
    dk = _FakeDK(
        detail={"contestDetail": {"name": "FromDetail", "draftGroupId": 9}}, standings_rows=[["header"], ["row"]]
    )

    raw = _collect(monkeypatch, tmp_path, contest_db=None, dk=dk, contest_id=999)

    assert raw["contest"]["name"] == "FromDetail"
    assert raw["candidates"] == []
