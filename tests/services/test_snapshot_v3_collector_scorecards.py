"""players[] scorecard facts from the VIP Scorecards, joined by draftable id."""

import time
from types import SimpleNamespace

import pytest

from dk_results.persistence.contestdatabase import ContestRow
from dk_results.services.snapshot_v3 import collector
from tests.services.snapshot_v3_collector_fakes import _by_name, _FakeContestDB, _FakeDK, _salary_player


def _sc_row(draftable_id, name="Player", **overrides) -> dict:
    """A Scorecard row as DraftKings sends it for a held player."""
    row = {
        "displayName": name,
        "rosterPosition": "QB",
        "score": "10.5",
        "percentDrafted": 50,
        "draftableId": draftable_id,
        "statsDescription": "1 PaTD, 286 PaYds",
        "timeRemaining": 45,
        "timeRemainingUnit": "PMR",
        "projection": {"realTimeProjection": 21.456, "pregameProjection": 19.0, "valueIcon": "fire"},
    }
    row.update(overrides)
    return row


class _ScorecardDK(_FakeDK):
    """FakeDK that also serves per-entry Scorecards; ``delays`` makes chosen entries answer last."""

    def __init__(self, scorecards, delays=None):
        super().__init__()
        self._scorecards = scorecards
        self._delays = delays or {}
        self.entry_requests: list[str] = []

    def get_entry(self, _draft_group, entry_key, *, timeout=None, session=None):
        time.sleep(self._delays.get(entry_key, 0))
        self.entry_requests.append(entry_key)
        return {"entries": [{"roster": {"scorecards": self._scorecards[entry_key]}}]}

    def clone_auth_to(self, _session):
        return None


def _collect_with_scorecards(monkeypatch, tmp_path, *, players, scorecards, delays=None):
    monkeypatch.setattr(collector, "SALARY_DIR", str(tmp_path))
    monkeypatch.setattr(collector, "load_vips", lambda: [f"vip{key}" for key in scorecards])
    dk = _ScorecardDK(scorecards, delays)
    results = SimpleNamespace(
        vip_list=[SimpleNamespace(name=f"vip{key}", player_id=key, pmr=0, rank=1, pts=0.0) for key in scorecards],
        players={player.name: player for player in players},
        users=[],
        non_cashing_users=0,
        non_cashing_avg_pmr=None,
        min_rank=0,
        min_cash_pts=0.0,
        non_cashing_players={},
    )
    monkeypatch.setattr(collector, "parse_contest_standings", lambda *a, **k: results)
    row = ContestRow(
        dk_id=321,
        name="Contest",
        draft_group=154161,
        positions_paid=10,
        start_date="2026-10-03",
        entry_fee=5,
        entries=100,
    )
    raw = collector._collect_source_snapshot(sport="NFL", contest_id=321, dk=dk, contest_db=_FakeContestDB(by_id=row))
    return _by_name(raw["players"]), dk, raw


def _pool(*ids_and_names) -> list:
    return [_salary_player(name, "BUF", "Final", draftable_id) for draftable_id, name in ids_and_names]


def test_held_player_gets_stats_text_and_value_icon_and_others_get_none(monkeypatch, tmp_path) -> None:
    rows, dk, raw = _collect_with_scorecards(
        monkeypatch,
        tmp_path,
        players=_pool(("11", "Held"), ("22", "Unheld")),
        scorecards={"100": [_sc_row(11, "Held")]},
    )

    assert rows["Held"]["stats_text"] == "1 PaTD, 286 PaYds"
    assert rows["Held"]["value_icon"] == "fire"
    assert "stats_text" not in rows["Unheld"] and "value_icon" not in rows["Unheld"]
    assert "draftable_id" not in rows["Held"]
    assert dk.entry_requests == ["100"]  # one fetch per VIP


def test_unusable_scorecard_rows_contribute_nothing(monkeypatch, tmp_path) -> None:
    scorecards = {
        "100": [
            {"displayName": "", "draftableId": 11, "statsDescription": "ghost", "projection": {"valueIcon": "fire"}},
            _sc_row(None, "No Id"),
            _sc_row(999, "Unmatched"),
        ]
    }
    rows, _, _ = _collect_with_scorecards(
        monkeypatch, tmp_path, players=_pool(("11", "Locked"), ("33", "No Id")), scorecards=scorecards
    )

    for row in rows.values():
        assert "stats_text" not in row and "value_icon" not in row


def test_empty_or_unrecognised_values_are_omitted(monkeypatch, tmp_path) -> None:
    scorecards = {
        "100": [
            _sc_row(11, "Empty", statsDescription="", projection={"valueIcon": ""}),
            _sc_row(22, "Odd", statsDescription=None, projection={"valueIcon": "lava"}),
            _sc_row(33, "Cold", projection={"valueIcon": "ice"}),
        ]
    }
    rows, _, _ = _collect_with_scorecards(
        monkeypatch, tmp_path, players=_pool(("11", "Empty"), ("22", "Odd"), ("33", "Cold")), scorecards=scorecards
    )

    assert "stats_text" not in rows["Empty"] and "value_icon" not in rows["Empty"]
    assert "stats_text" not in rows["Odd"] and "value_icon" not in rows["Odd"]
    assert rows["Cold"]["value_icon"] == "ice"


def test_two_vips_holding_one_player_lowest_entry_key_wins_whatever_the_fetch_order(monkeypatch, tmp_path) -> None:
    scorecards = {
        "100": [_sc_row(11, "Held", statsDescription="from 100", projection={"valueIcon": ""})],
        "200": [_sc_row(11, "Held", statsDescription="from 200", projection={"valueIcon": "ice"})],
    }
    # entry 100 answers last, so the fetch completes in the opposite order
    rows, _, _ = _collect_with_scorecards(
        monkeypatch, tmp_path, players=_pool(("11", "Held")), scorecards=scorecards, delays={"100": 0.2}
    )

    assert rows["Held"]["stats_text"] == "from 100"
    assert rows["Held"]["value_icon"] == "ice"  # first non-empty value per field


def test_held_player_gets_unrounded_projection_and_pmr_minutes(monkeypatch, tmp_path) -> None:
    rows, _, _ = _collect_with_scorecards(
        monkeypatch,
        tmp_path,
        players=_pool(("11", "Held"), ("22", "Unheld")),
        scorecards={"100": [_sc_row(11, "Held")]},
    )

    assert rows["Held"]["rt_projection"] == 21.456
    assert rows["Held"]["time_remaining_minutes"] == 45
    assert "rt_projection" not in rows["Unheld"] and "time_remaining_minutes" not in rows["Unheld"]


def test_zero_projection_and_zero_minutes_are_emitted(monkeypatch, tmp_path) -> None:
    row = _sc_row(11, "Done", timeRemaining=0, projection={"realTimeProjection": 0, "valueIcon": ""})
    rows, _, _ = _collect_with_scorecards(
        monkeypatch, tmp_path, players=_pool(("11", "Done")), scorecards={"100": [row]}
    )

    assert rows["Done"]["rt_projection"] == 0
    assert rows["Done"]["time_remaining_minutes"] == 0


@pytest.mark.parametrize("raw", ["", None, "n/a", True, float("nan")])
def test_empty_or_unparseable_projection_is_omitted(monkeypatch, tmp_path, raw) -> None:
    row = _sc_row(11, "Held", projection={"realTimeProjection": raw})
    rows, _, _ = _collect_with_scorecards(
        monkeypatch, tmp_path, players=_pool(("11", "Held")), scorecards={"100": [row]}
    )

    assert "rt_projection" not in rows["Held"]


@pytest.mark.parametrize(
    "overrides",
    [
        {"timeRemainingUnit": "MIN"},
        {"timeRemainingUnit": ""},
        {"timeRemaining": ""},
        {"timeRemaining": "Q4 2:00"},
        {"timeRemaining": None},
    ],
)
def test_minutes_omitted_unless_a_pmr_number(monkeypatch, tmp_path, overrides) -> None:
    row = _sc_row(11, "Held", **overrides)
    rows, _, _ = _collect_with_scorecards(
        monkeypatch, tmp_path, players=_pool(("11", "Held")), scorecards={"100": [row]}
    )

    assert "time_remaining_minutes" not in rows["Held"]


def test_locked_and_unmatched_rows_contribute_no_projection_or_minutes(monkeypatch, tmp_path) -> None:
    scorecards = {"100": [_sc_row(11, ""), _sc_row(None, "No Id"), _sc_row(999, "Unmatched")]}
    rows, _, _ = _collect_with_scorecards(
        monkeypatch, tmp_path, players=_pool(("11", "Locked"), ("33", "No Id")), scorecards=scorecards
    )

    for row in rows.values():
        assert "rt_projection" not in row and "time_remaining_minutes" not in row


def test_projection_and_minutes_follow_the_lowest_entry_key_per_field(monkeypatch, tmp_path) -> None:
    low = _sc_row(11, "Held", timeRemaining="", projection={"realTimeProjection": 5.5})
    high = _sc_row(11, "Held", timeRemaining=30, projection={"realTimeProjection": 9.9})
    rows, _, _ = _collect_with_scorecards(
        monkeypatch,
        tmp_path,
        players=_pool(("11", "Held")),
        scorecards={"100": [low], "200": [high]},
        delays={"100": 0.2},
    )

    assert rows["Held"]["rt_projection"] == 5.5
    assert rows["Held"]["time_remaining_minutes"] == 30
