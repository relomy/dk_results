from types import SimpleNamespace

from dk_results.persistence.contestdatabase import ContestRow
from dk_results.services.snapshot_v3 import collector
from dk_results.services.snapshot_v3.collector import (
    _apply_truncation,
    _build_vip_points_by_entry,
    _compute_ownership_remaining_total,
    _fetch_leaderboard_payouts,
    _leaderboard_row_payout_cents,
    _select_contest,
    collect_raw_bundle,
)
from dk_results.services.snapshot_v3.derive import derive_threat


class _FakeDK:
    """DraftKings edge stub: no network, records the salary path it was handed."""

    def __init__(self, *, detail=None, leaderboard=None, standings_rows=None):
        self._detail = detail or {}
        self._leaderboard = leaderboard if leaderboard is not None else {}
        self.standings_rows = standings_rows if standings_rows is not None else [["header"], ["row"]]
        self.salary_path = None

    def get_contest_detail(self, _contest_id):
        return self._detail

    def get_leaderboard(self, _contest_id):
        return self._leaderboard

    def download_salary_csv(self, _name, _draft_group, path):
        with open(path, "w", newline="", encoding="utf-8") as handle:
            handle.write("Position,Name+ID,Name,ID,Roster Position,Salary,Game Info,TeamAbbrev,AvgPointsPerGame\n")
        self.salary_path = path

    def download_contest_rows(self, _dk_id, timeout=30, cookies_dump_file=None, contest_dir=None):
        return self.standings_rows


class _FakeContestDB:
    """In-memory ContestDatabase edge stub."""

    def __init__(self, *, by_id=None, candidates=None, live=None, state=None, contract=None):
        self._by_id = by_id
        self._candidates = candidates or []
        self._live = live
        self._state = state
        self._contract = contract
        self.closed = False

    def get_live_contest_candidates(self, _name, entry_fee=None, keyword=None, limit=None):
        return self._candidates

    def get_contest_by_id(self, _contest_id):
        return self._by_id

    def get_live_contest(self, _name, _min_fee, _keyword):
        return self._live

    def get_contest_state(self, _dk_id):
        return self._state

    def get_contest_contract_metadata(self, _dk_id):
        return self._contract

    def close(self):
        self.closed = True


def test_leaderboard_payout_parser_sums_cash_winnings_and_ignores_non_cash() -> None:
    assert (
        _leaderboard_row_payout_cents(
            {
                "winnings": [
                    {"payoutType": "CASH", "winningValue": "12.34"},
                    {"payoutType": "TICKET", "winningValue": "5.00"},
                    {"payoutType": "CASH", "winningValue": "0.66"},
                ]
            }
        )
        == 1300
    )


def test_leaderboard_payout_parser_prefers_scalar_winning_value() -> None:
    assert _leaderboard_row_payout_cents({"winningValue": "3.25", "winnings": [{"winningValue": "99.00"}]}) == 325


def test_collect_raw_bundle_returns_expected_raw_shape(monkeypatch) -> None:
    monkeypatch.setattr(
        "dk_results.services.snapshot_v3.collector._collect_source_snapshot",
        lambda **_kwargs: {
            "sport": "NBA",
            "contest": {"contest_id": "123", "name": "Contest"},
            "selection": {"selected_contest_id": "123", "reason": {"mode": "explicit_id"}},
            "standings": [{"entry_key": "e1"}],
            "vip_lineups": [{"entry_key": "e1"}],
            "train_clusters": [{"cluster_id": "c1", "entry_keys": ["e1"]}],
            "players": [{"name": "A"}],
            "cash_line": {"points": 250.0},
            "ownership": {"watchlist_entries": []},
            "metadata": {"warnings": []},
            "truncation": {"applied": False},
            "candidates": [],
        },
    )

    raw = collect_raw_bundle(sport="NBA", contest_id=123, standings_limit=10)

    assert raw["sport"] == "NBA"
    assert raw["contest"]["contest_id"] == "123"
    assert raw["selected_contest_id"] == "123"
    assert raw["standings"] == [{"entry_key": "e1"}]
    assert raw["vip_lineups"] == [{"entry_key": "e1", "vip_entry_key": "e1"}]
    assert raw["train_clusters"] == [{"cluster_id": "c1", "entry_keys": ["e1"]}]


def test_collect_raw_bundle_keeps_vips_without_entry_key_and_does_not_truncate_trains(monkeypatch) -> None:
    monkeypatch.setattr(
        "dk_results.services.snapshot_v3.collector._collect_source_snapshot",
        lambda **_kwargs: {
            "sport": "NBA",
            "contest": {"contest_id": "123", "name": "Contest"},
            "selection": {"selected_contest_id": "123", "reason": {"mode": "explicit_id"}},
            "standings": [{"entry_key": "e1"}, {"entry_key": "e2"}],
            "vip_lineups": [
                {"entry_key": "e1", "display_name": "keep"},
                {"user": "vip-without-key", "players": [{"name": "A"}]},
            ],
            "train_clusters": [
                {"cluster_id": "c1", "entry_keys": ["e1", "x9"]},
                {"cluster_id": "c2", "entry_keys": ["x9"]},
            ],
            "players": [],
            "cash_line": {},
            "ownership": {},
            "metadata": {},
            "truncation": {},
            "candidates": [],
        },
    )

    raw = collect_raw_bundle(sport="NBA", contest_id=123, standings_limit=10)

    assert raw["vip_lineups"] == [
        {"entry_key": "e1", "vip_entry_key": "e1", "display_name": "keep"},
        {
            "display_name": "vip-without-key",
            "players_live": [{"player_name": "A", "player_key": "nba:a:na:na:na", "is_live": False}],
        },
    ]
    assert raw["train_clusters"] == [
        {"cluster_id": "c1", "entry_keys": ["e1", "x9"]},
        {"cluster_id": "c2", "entry_keys": ["x9"]},
    ]


def test_collect_raw_bundle_does_not_backfill_entry_key_from_ambiguous_display_name(monkeypatch) -> None:
    monkeypatch.setattr(
        "dk_results.services.snapshot_v3.collector._collect_source_snapshot",
        lambda **_kwargs: {
            "sport": "NBA",
            "contest": {"contest_id": "123", "name": "Contest"},
            "selection": {"selected_contest_id": "123", "reason": {"mode": "explicit_id"}},
            "standings": [
                {"entry_key": "e1", "username": "dup-user"},
                {"entry_key": "e2", "username": "dup-user"},
            ],
            "vip_lineups": [
                {"user": "dup-user", "players": [{"name": "A"}]},
            ],
            "train_clusters": [],
            "players": [],
            "cash_line": {},
            "ownership": {},
            "metadata": {},
            "truncation": {},
            "candidates": [],
        },
    )

    raw = collect_raw_bundle(sport="NBA", contest_id=123, standings_limit=10)

    assert raw["vip_lineups"] == [
        {
            "display_name": "dup-user",
            "players_live": [{"player_name": "A", "player_key": "nba:a:na:na:na", "is_live": False}],
        }
    ]


def test_collect_raw_bundle_marks_textual_live_status_as_live(monkeypatch) -> None:
    monkeypatch.setattr(
        "dk_results.services.snapshot_v3.collector._collect_source_snapshot",
        lambda **_kwargs: {
            "sport": "NBA",
            "contest": {"contest_id": "123", "name": "Contest"},
            "selection": {"selected_contest_id": "123", "reason": {"mode": "explicit_id"}},
            "standings": [],
            "vip_lineups": [
                {
                    "user": "vip1",
                    "players": [
                        {"name": "Player A", "salary": "$10,300", "timeStatus": "In Progress"},
                        {"name": "Player B", "salary": "$9,100", "timeStatus": "Final"},
                    ],
                }
            ],
            "train_clusters": [],
            "players": [],
            "cash_line": {},
            "ownership": {},
            "metadata": {},
            "truncation": {},
            "candidates": [],
        },
    )

    raw = collect_raw_bundle(sport="NBA", contest_id=123, standings_limit=10)
    players_live = raw["vip_lineups"][0]["players_live"]

    assert players_live[0]["player_name"] == "Player A"
    assert players_live[0]["is_live"] is True
    assert players_live[1]["player_name"] == "Player B"
    assert players_live[1]["is_live"] is False


def test_collect_raw_bundle_maps_top_remaining_players_from_vip_slots_when_players_missing(monkeypatch) -> None:
    monkeypatch.setattr(
        "dk_results.services.snapshot_v3.collector._collect_source_snapshot",
        lambda **_kwargs: {
            "sport": "NBA",
            "contest": {"contest_id": "123", "name": "Contest"},
            "selection": {"selected_contest_id": "123", "reason": {"mode": "explicit_id"}},
            "standings": [],
            "vip_lineups": [
                {
                    "user": "vip1",
                    "players": [
                        {"name": "Player A", "salary": "$10,300", "timeStatus": "In Progress"},
                    ],
                }
            ],
            "train_clusters": [],
            "players": [],
            "cash_line": {},
            "ownership": {
                "non_cashing_top_remaining_players": [{"player_name": "Player A", "ownership_remaining_pct": 80.0}]
            },
            "metadata": {},
            "truncation": {},
            "candidates": [],
        },
    )

    raw = collect_raw_bundle(sport="NBA", contest_id=123, standings_limit=10)
    vip_slot = raw["vip_lineups"][0]["players_live"][0]
    top_row = raw["ownership"]["non_cashing_top_remaining_players"][0]
    threat = derive_threat(raw)

    assert vip_slot["player_key"] == "nba:player-a:na:10300:na"
    assert top_row["player_key"] == "nba:player-a:na:10300:na"
    assert threat == {
        "top_swing_players": [
            {
                "player_key": "nba:player-a:na:10300:na",
                "player_name": "Player A",
                "ownership_remaining_pct": 80.0,
                "vip_count": 1,
            }
        ]
    }


# --- extracted collector helpers -------------------------------------------------


def test_fetch_leaderboard_payouts_maps_entries() -> None:
    dk = _FakeDK(leaderboard={"contestStandings": [{"entryKey": "e1", "winningValue": "1.00"}]})
    assert _fetch_leaderboard_payouts(dk, 5) == {"e1": 100}


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


# --- contest selection -----------------------------------------------------------


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


# --- orchestrator through the injectable seam ------------------------------------


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
