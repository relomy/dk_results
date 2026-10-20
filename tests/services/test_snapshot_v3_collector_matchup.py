"""players[].matchup from draftables through the injectable seam."""

import logging
from types import SimpleNamespace

from dk_results.persistence.contestdatabase import ContestRow
from dk_results.services.snapshot_v3 import collector
from tests.domain.draftables_payloads import cfb_payload, golf_payload
from tests.services.snapshot_v3_collector_fakes import _by_name, _FakeContestDB, _FakeDK, _salary_player


def _collect_players(monkeypatch, tmp_path, *, sport, players, dk) -> list[dict]:
    monkeypatch.setattr(collector, "SALARY_DIR", str(tmp_path))
    monkeypatch.setattr(collector, "load_vips", lambda: [])
    monkeypatch.setattr(collector, "fetch_vip_lineups", lambda *a, **k: [])
    results = SimpleNamespace(
        vip_list=[],
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
    raw = collector._collect_source_snapshot(sport=sport, contest_id=321, dk=dk, contest_db=_FakeContestDB(by_id=row))
    return raw["players"]


def test_players_get_opponent_from_draftables_before_during_and_after_their_game(monkeypatch, tmp_path) -> None:
    dk = _FakeDK(draftables=cfb_payload())
    players = [
        _salary_player("Kamario Taylor", "MSST", "Final", "44324334"),
        _salary_player("Keelon Russell", "BAMA", "Final", "44324318"),
        _salary_player("Jamal Roberts", "MIZZ", "In-Progress", "44324599"),
        _salary_player("Jadan Baugh", "UF", "UF@MIZZ 10/03/2026 03:30PM ET", "44324584"),
    ]

    rows = _by_name(_collect_players(monkeypatch, tmp_path, sport="CFB", players=players, dk=dk))

    assert rows["Kamario Taylor"]["matchup"] == "vs. BAMA"
    assert rows["Keelon Russell"]["matchup"] == "at MSST"
    assert rows["Jamal Roberts"]["matchup"] == "vs. UF"
    assert rows["Jadan Baugh"]["matchup"] == "at MIZZ"
    assert rows["Kamario Taylor"]["game_status"] == "Final"  # game_status is unchanged
    assert all(row["matchup"] != row["game_status"] for row in rows.values())
    assert dk.draftables_requests == [154161]  # one draftables request for the sport


def test_golf_players_have_no_matchup(monkeypatch, tmp_path) -> None:
    dk = _FakeDK(draftables=golf_payload())
    players = [
        _salary_player("Benjamin James", "Golf", "Bank of Utah Championship", "44384982"),
        _salary_player("Jackson Koivun", "Golf", "In-Progress", "44384983"),
    ]

    rows = _collect_players(monkeypatch, tmp_path, sport="GOLF", players=players, dk=dk)

    assert [row["name"] for row in rows] == ["Benjamin James", "Jackson Koivun"]
    assert all("matchup" not in row for row in rows)


def test_player_missing_from_draftables_has_no_matchup(monkeypatch, tmp_path) -> None:
    dk = _FakeDK(draftables=cfb_payload())
    players = [
        _salary_player("Kamario Taylor", "MSST", "Final", "44324334"),
        _salary_player("Not In Payload", "MSST", "Final", "99999999"),
        _salary_player("No Salary ID", "MSST", "Final", None),
    ]

    rows = _by_name(_collect_players(monkeypatch, tmp_path, sport="CFB", players=players, dk=dk))

    assert rows["Kamario Taylor"]["matchup"] == "vs. BAMA"
    assert "matchup" not in rows["Not In Payload"]
    assert "matchup" not in rows["No Salary ID"]


def test_player_on_neither_competition_team_has_no_matchup(monkeypatch, tmp_path) -> None:
    payload = cfb_payload()
    payload["draftables"][2]["teamAbbreviation"] = "UGA"  # 44324334
    dk = _FakeDK(draftables=payload)
    players = [_salary_player("Kamario Taylor", "UGA", "Final", "44324334")]

    rows = _collect_players(monkeypatch, tmp_path, sport="CFB", players=players, dk=dk)

    assert "matchup" not in rows[0]


def _fail_http():
    import requests

    return requests.HTTPError("503 Server Error")


def _fail_validation():
    return {"draftables": [{"draftableId": 1}], "competitions": []}  # missing required fields


def test_failed_draftables_read_logs_one_warning_and_snapshot_still_builds(monkeypatch, tmp_path, caplog) -> None:
    players = [
        _salary_player("Kamario Taylor", "MSST", "Final", "44324334"),
        _salary_player("Jadan Baugh", "UF", "UF@MIZZ 10/03/2026 03:30PM ET", "44324584"),
    ]
    cases = [_FakeDK(draftables_error=_fail_http()), _FakeDK(draftables=_fail_validation())]

    for dk in cases:
        caplog.clear()
        with caplog.at_level(logging.WARNING, logger=collector.logger.name):
            rows = _collect_players(monkeypatch, tmp_path, sport="CFB", players=players, dk=dk)

        assert [row["name"] for row in rows] == ["Jadan Baugh", "Kamario Taylor"]
        assert all("matchup" not in row for row in rows)
        warnings = [record for record in caplog.records if record.levelno == logging.WARNING]
        assert len(warnings) == 1
        assert "draftables" in warnings[0].getMessage()
        assert dk.draftables_requests == [154161]
