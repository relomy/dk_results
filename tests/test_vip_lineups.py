from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

import dk_results.vip_lineups as vip_mod
from dk_results.vip_lineups import (
    VipLineup,
    VipPlayer,
    _lookup_salary,
    _normalize_name,
    _parse_scorecard,
    build_vip_entries,
    fetch_vip_lineups,
    load_vips,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────


def _scorecard_entry(
    *,
    display_name: str = "Player A",
    roster_position: str = "RB",
    score: Any = "10.5",
    percent_drafted: Any = 50,
    rt_proj: Any = "12.0",
    pregame_proj: Any = "11.0",
    value_icon: str = "",
    time_remaining: str = "Q4 2:00",
    stats: str = "10 car, 80 yds",
    salary: Any = None,
) -> dict[str, Any]:
    return {
        "displayName": display_name,
        "rosterPosition": roster_position,
        "score": score,
        "percentDrafted": percent_drafted,
        "timeRemaining": time_remaining,
        "statsDescription": stats,
        "salary": salary,
        "projection": {
            "realTimeProjection": rt_proj,
            "pregameProjection": pregame_proj,
            "valueIcon": value_icon,
        },
    }


def _scorecard_response(*scorecards: dict[str, Any]) -> dict[str, Any]:
    return {"entries": [{"roster": {"scorecards": list(scorecards)}}]}


class _FakeHttp:
    def __init__(
        self,
        leaderboard: dict[str, Any] | None = None,
        scorecard: dict[str, Any] | None = None,
        raise_on_entry: Exception | None = None,
    ):
        self._lb = leaderboard or {"leaderBoard": []}
        self._sc = scorecard or {"entries": []}
        self._raise = raise_on_entry

    def get_leaderboard(self, contest_id: int, *, timeout: int | None = None) -> dict[str, Any]:
        return self._lb

    def get_entry(
        self, draft_group: int, entry_key: str, *, timeout: int | None = None, session=None
    ) -> dict[str, Any]:
        if self._raise is not None:
            raise self._raise
        return self._sc

    def clone_auth_to(self, target_session) -> None:
        pass


# ── _normalize_name ───────────────────────────────────────────────────────────


def test_normalize_name_strips_accents():
    assert _normalize_name("José") == "Jose"
    assert _normalize_name("Ångström") == "Angstrom"


def test_normalize_name_non_string_returns_empty():
    assert _normalize_name(123) == ""  # type: ignore[arg-type]


# ── _lookup_salary ────────────────────────────────────────────────────────────


def test_lookup_salary_exact_match():
    assert _lookup_salary("Tom Brady", {"Tom Brady": 7000}) == 7000


def test_lookup_salary_accent_normalization():
    assert _lookup_salary("José Ramírez", {"Jose Ramirez": 5500}) == 5500


def test_lookup_salary_empty_name():
    assert _lookup_salary("", {"Tom Brady": 7000}) is None


def test_lookup_salary_no_map():
    assert _lookup_salary("Tom Brady", None) is None


def test_lookup_salary_missing_name():
    assert _lookup_salary("Unknown Player", {"Tom Brady": 7000}) is None


# ── load_vips ─────────────────────────────────────────────────────────────────


def test_load_vips_reads_yaml(tmp_path, monkeypatch):
    (tmp_path / "vips.yaml").write_text("- Alice\n- Bob\n", encoding="utf-8")
    monkeypatch.setattr(vip_mod, "repo_file", lambda *parts: tmp_path.joinpath(*parts))
    assert load_vips() == ["Alice", "Bob"]


def test_load_vips_missing_file_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(vip_mod, "repo_file", lambda *parts: tmp_path.joinpath(*parts))
    assert load_vips() == []


def test_load_vips_non_list_yaml_returns_empty(tmp_path, monkeypatch):
    (tmp_path / "vips.yaml").write_text("not_a_list: true\n", encoding="utf-8")
    monkeypatch.setattr(vip_mod, "repo_file", lambda *parts: tmp_path.joinpath(*parts))
    assert load_vips() == []


def test_load_vips_strips_whitespace(tmp_path, monkeypatch):
    (tmp_path / "vips.yaml").write_text("- '  Alice  '\n- Bob\n", encoding="utf-8")
    monkeypatch.setattr(vip_mod, "repo_file", lambda *parts: tmp_path.joinpath(*parts))
    assert load_vips() == ["Alice", "Bob"]


# ── build_vip_entries ─────────────────────────────────────────────────────────


def _vip_user(name, player_id, pmr="", rank="", pts=""):
    return SimpleNamespace(name=name, player_id=player_id, pmr=pmr, rank=rank, pts=pts)


def test_build_vip_entries_basic():
    vip_list = [_vip_user("Alice", "ek1", pmr="5", rank="1", pts="300")]
    entries = build_vip_entries(vip_list)
    assert entries == {"Alice": {"entry_key": "ek1", "pmr": "5", "rank": "1", "pts": "300"}}


def test_build_vip_entries_skips_missing_name_or_id():
    vip_list = [
        _vip_user("", "ek1"),
        _vip_user("Alice", ""),
        _vip_user("Bob", "ek2"),
    ]
    entries = build_vip_entries(vip_list)
    assert list(entries.keys()) == ["Bob"]


# ── _parse_scorecard ──────────────────────────────────────────────────────────


def test_parse_scorecard_basic():
    sc = _scorecard_response(_scorecard_entry(score="10.5", percent_drafted=50))
    players, total = _parse_scorecard(sc, None)
    assert len(players) == 1
    p = players[0]
    assert p.name == "Player A"
    assert p.pts == "10.5"
    assert p.ownership == 0.5
    assert total == 0


def test_parse_scorecard_uses_salary_map():
    sc = _scorecard_response(_scorecard_entry(score="20", percent_drafted=30))
    players, total = _parse_scorecard(sc, {"Player A": 6000})
    assert players[0].salary == 6000
    assert total == 6000
    assert players[0].value == f"{20.0 / 6.0:.2f}"


def test_parse_scorecard_uses_inline_salary_when_no_map():
    sc = _scorecard_response(_scorecard_entry(score="10", percent_drafted=50, salary=5000))
    players, total = _parse_scorecard(sc, None)
    assert players[0].salary == 5000
    assert total == 5000


def test_parse_scorecard_locked_player():
    sc = _scorecard_response({"rosterPosition": "FLEX", "projection": {}})
    players, _ = _parse_scorecard(sc, None)
    assert players[0].name == "LOCKED 🔒"


def test_parse_scorecard_no_entries_returns_empty():
    players, total = _parse_scorecard({"entries": []}, None)
    assert players == []
    assert total == 0


def test_parse_scorecard_invalid_score_value_clears_value():
    sc = _scorecard_response(_scorecard_entry(score="bad", rt_proj="bad"))
    players, _ = _parse_scorecard(sc, {"Player A": 4000})
    assert players[0].value == ""
    assert players[0].rt_proj == "bad"


def test_parse_scorecard_rt_proj_none_becomes_empty():
    sc = _scorecard_response(_scorecard_entry(rt_proj=None))
    players, _ = _parse_scorecard(sc, None)
    assert players[0].rt_proj == ""


# ── fetch_vip_lineups — entry path ────────────────────────────────────────────


def test_fetch_vip_lineups_entry_path_returns_typed_lineup():
    sc = _scorecard_response(_scorecard_entry(score="15", percent_drafted=40))
    http = _FakeHttp(scorecard=sc)
    result = fetch_vip_lineups(
        1,
        2,
        http,
        vip_entries={"Alice": {"entry_key": "ek1", "pmr": "5", "rank": "1", "pts": "300"}},
    )
    assert len(result) == 1
    lineup = result[0]
    assert isinstance(lineup, VipLineup)
    assert lineup.user == "Alice"
    assert lineup.entry_key == "ek1"
    assert len(lineup.players) == 1
    assert isinstance(lineup.players[0], VipPlayer)


def test_fetch_vip_lineups_skips_empty_entry_key():
    http = _FakeHttp()
    result = fetch_vip_lineups(1, 2, http, vip_entries={"Alice": {"entry_key": ""}})
    assert result == []


def test_fetch_vip_lineups_no_roster_data_excluded():
    http = _FakeHttp(scorecard={"entries": []})
    result = fetch_vip_lineups(
        1,
        2,
        http,
        vip_entries={"Alice": {"entry_key": "ek1"}},
    )
    assert result == []


def test_fetch_vip_lineups_worker_exception_swallowed():
    http = _FakeHttp(raise_on_entry=RuntimeError("network error"))
    result = fetch_vip_lineups(
        1,
        2,
        http,
        vip_entries={"Alice": {"entry_key": "ek1"}},
    )
    assert result == []


# ── fetch_vip_lineups — leaderboard path ─────────────────────────────────────


def test_fetch_vip_lineups_leaderboard_path_filters_by_vip_set():
    lb = {
        "leaderBoard": [
            {"userName": "Alice", "entryKey": "ek1", "rank": "1", "fantasyPoints": "300", "timeRemaining": "0"},
            {"userName": "Carol", "entryKey": "ek2", "rank": "2", "fantasyPoints": "280", "timeRemaining": "0"},
        ]
    }
    sc = _scorecard_response(_scorecard_entry())
    http = _FakeHttp(leaderboard=lb, scorecard=sc)
    result = fetch_vip_lineups(1, 2, http, vips=["Alice"])
    assert len(result) == 1
    assert result[0].user == "Alice"


def test_fetch_vip_lineups_no_matching_vips_returns_empty():
    lb = {"leaderBoard": [{"userName": "Carol", "entryKey": "ek2"}]}
    http = _FakeHttp(leaderboard=lb)
    result = fetch_vip_lineups(1, 2, http, vips=["Alice"])
    assert result == []


# ── VipLineup.to_dict ─────────────────────────────────────────────────────────


def test_vip_lineup_to_dict_shape():
    player = VipPlayer(
        pos="RB",
        name="Tom Brady",
        pts="20.5",
        salary=7000,
        value="2.93",
        ownership=0.5,
        rt_proj="22.0",
        pregame_proj="18.0",
        time_status="In Progress",
        value_icon="fire",
        stats="10 car",
    )
    lineup = VipLineup(
        user="Alice",
        rank="1",
        pts="300",
        pmr="5",
        entry_key="ek1",
        total_salary=7000,
        players=[player],
    )
    d = lineup.to_dict()
    assert d["user"] == "Alice"
    assert d["entry_key"] == "ek1"
    assert d["salary"] == 7000
    assert len(d["players"]) == 1
    p = d["players"][0]
    assert p["name"] == "Tom Brady"
    assert p["rtProj"] == "22.0"
    assert p["valueIcon"] == "fire"
    assert p["timeStatus"] == "In Progress"


def test_vip_player_to_dict_none_salary_becomes_empty_string():
    player = VipPlayer(
        pos="QB",
        name="LOCKED 🔒",
        pts="0",
        salary=None,
        value="",
        ownership="",
        rt_proj="",
        pregame_proj="",
        time_status="",
        value_icon="",
        stats="",
    )
    assert player.to_dict()["salary"] == ""
