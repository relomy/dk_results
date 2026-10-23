"""Typed VIP lineups from the fetcher survive collection."""

from types import SimpleNamespace

import pytest

from dk_results.persistence.contestdatabase import ContestRow
from dk_results.services.snapshot_v3 import collector
from dk_results.services.snapshot_v3.collector import collect_snapshot
from dk_results.services.snapshot_v3.pipeline import build_snapshot_v3_envelope
from dk_results.vip_lineups import VipLineup, VipPlayer
from tests.services.snapshot_v3_collector_fakes import _FakeContestDB, _FakeDK


def _typed_vip_lineup() -> VipLineup:
    return VipLineup(
        user="vipuser",
        rank="5",
        pts=130.0,
        pmr="120",
        entry_key="e1",
        total_salary=15000,
        players=[
            VipPlayer(
                pos="QB",
                name="Player A",
                pts=20.0,
                salary=8000,
                value=2.5,
                ownership=12.5,
                rt_proj="21.0",
                pregame_proj=19.0,
                time_status="45",
                value_icon="",
                stats="",
            ),
            VipPlayer(
                pos="RB",
                name="Player B",
                pts=10.0,
                salary=7000,
                value=1.4,
                ownership=8.0,
                rt_proj="0",
                pregame_proj=12.0,
                time_status="0",
                value_icon="",
                stats="",
            ),
            VipPlayer(
                pos="UTIL",
                name="LOCKED 🔒",
                pts=0.0,
                salary=None,
                value=0.0,
                ownership=0.0,
                rt_proj="",
                pregame_proj="",
                time_status="",
                value_icon="",
                stats="",
            ),
        ],
    )


def _collect_typed_vip_bundle(
    monkeypatch, tmp_path, *, lineup=None, lineups=None, extra_users=(), standings_limit=None
) -> dict:
    monkeypatch.setattr(collector, "SALARY_DIR", str(tmp_path))
    monkeypatch.setattr(collector, "load_vips", lambda: ["vipuser"])
    fetched = lineups if lineups is not None else [lineup or _typed_vip_lineup()]
    monkeypatch.setattr(collector, "fetch_vip_lineups", lambda *a, **k: list(fetched))
    vip_user = SimpleNamespace(
        rank="5",
        player_id="e1",
        name="vipuser",
        pmr="120",
        pts=100.0,
        salary=50000,
        lineupobj=None,
        lineup=[],
    )
    results = SimpleNamespace(
        vip_list=[vip_user],
        players={},
        users=[vip_user, *extra_users],
        non_cashing_users=0,
        non_cashing_avg_pmr=None,
        min_rank=10,
        min_cash_pts=120.0,
        non_cashing_players={},
    )
    monkeypatch.setattr(collector, "parse_contest_standings", lambda *a, **k: results)
    row = ContestRow(
        dk_id=321,
        name="Contest",
        draft_group=8,
        positions_paid=10,
        start_date="2026-01-04",
        entry_fee=5,
        entries=100,
    )
    real_collect = collector._collect_source_snapshot
    monkeypatch.setattr(
        collector,
        "_collect_source_snapshot",
        lambda **kwargs: real_collect(dk=_FakeDK(), contest_db=_FakeContestDB(by_id=row), **kwargs),
    )

    kwargs = {} if standings_limit is None else {"standings_limit": standings_limit}
    return collect_snapshot(sport="NBA", contest_id=321, **kwargs).bundle


def test_collect_snapshot_keeps_typed_vip_lineups_from_the_fetcher(monkeypatch, tmp_path) -> None:
    bundle = _collect_typed_vip_bundle(monkeypatch, tmp_path)

    assert len(bundle["vip_lineups"]) == 1
    vip = bundle["vip_lineups"][0]
    assert (vip["display_name"], vip["entry_key"], vip["vip_entry_key"]) == ("vipuser", "e1", "e1")
    assert (vip["rank"], vip["points"], vip["pmr"]) == (5, 130.0, 120.0)
    assert "pts" not in vip


def _ranked_vip_lineup(user: str, entry_key: str, rank: str) -> VipLineup:
    lineup = _typed_vip_lineup()
    lineup.user, lineup.entry_key, lineup.rank = user, entry_key, rank
    return lineup


def test_collect_snapshot_orders_vip_lineups_by_rank_then_vip_entry_key(monkeypatch, tmp_path) -> None:
    # The fetcher returns lineups in worker-thread completion order.
    fetched = [
        _ranked_vip_lineup("slowpoke", "e9", "12"),
        _ranked_vip_lineup("unranked", "e0", ""),
        _ranked_vip_lineup("tiedlate", "e5", "3"),
        _ranked_vip_lineup("tiedearly", "e2", "3"),
    ]
    bundle = _collect_typed_vip_bundle(monkeypatch, tmp_path, lineups=fetched)

    assert [vip["vip_entry_key"] for vip in bundle["vip_lineups"]] == ["e2", "e5", "e9", "e0"]


def test_collect_snapshot_typed_vip_lineup_slots_carry_salary_and_live_state(monkeypatch, tmp_path) -> None:
    bundle = _collect_typed_vip_bundle(monkeypatch, tmp_path)

    slots = {slot["player_name"]: slot for slot in bundle["vip_lineups"][0]["players_live"]}
    assert (slots["Player A"]["slot"], slots["Player A"]["salary"], slots["Player A"]["is_live"]) == (
        "QB",
        8000,
        True,
    )
    assert slots["Player A"]["player_key"]
    assert (slots["Player B"]["slot"], slots["Player B"]["salary"], slots["Player B"]["is_live"]) == (
        "RB",
        7000,
        False,
    )


def test_collect_snapshot_typed_vip_lineup_locked_slot_omits_player_details(monkeypatch, tmp_path) -> None:
    bundle = _collect_typed_vip_bundle(monkeypatch, tmp_path)

    locked = bundle["vip_lineups"][0]["players_live"][2]
    assert locked == {"slot": "UTIL", "player_name": "LOCKED 🔒", "is_locked": True}


def test_collect_snapshot_vip_points_lookup_sees_typed_vip_lineup(monkeypatch, tmp_path) -> None:
    bundle = _collect_typed_vip_bundle(monkeypatch, tmp_path)

    # the VIP-points lookup sees the lineup's 130.0 (>= 120 cutoff), not the standings row's 100.0
    assert bundle["standings"][0]["is_cashing"] is True


def test_typed_vip_lineup_reaches_validated_snapshot_envelope(monkeypatch, tmp_path) -> None:
    bundle = _collect_typed_vip_bundle(monkeypatch, tmp_path)
    bundle["contest"]["state"] = "live"
    bundle["contest"]["prize_pool"] = 1000

    envelope = build_snapshot_v3_envelope(
        {"NBA": 321},
        generated_at="2026-10-04T12:00:00Z",
        collector=lambda **_: bundle,
    )
    vip = envelope["sports"]["nba"]["contests"][0]["vip_lineups"][0]

    assert (vip["vip_entry_key"], vip["entry_key"], vip["rank"], vip["points"]) == ("e1", "e1", 5, 130.0)
    assert [slot["slot"] for slot in vip["players_live"]] == ["QB", "RB", "UTIL"]
    assert vip["players_live"][2] == {"slot": "UTIL", "player_name": "LOCKED 🔒", "is_locked": True}
    assert envelope["sports"]["nba"]["contests"][0]["standings"][0]["is_cashing"] is True


def _prod_shaped_vip_lineup() -> VipLineup:
    lineup = _typed_vip_lineup()
    lineup.rank = "879"
    lineup.pmr = "390"
    lineup.pts = 28.64
    lineup.players[0].name = "Rams "
    return lineup


def _collect_vip_below_standings_limit(monkeypatch, tmp_path) -> dict:
    leader = SimpleNamespace(
        rank="1", player_id="e0", name="leader", pmr="0", pts=200.0, salary=0, lineupobj=None, lineup=[]
    )
    bundle = _collect_typed_vip_bundle(
        monkeypatch, tmp_path, lineup=_prod_shaped_vip_lineup(), extra_users=[leader], standings_limit=1
    )
    bundle["contest"]["state"] = "live"
    bundle["contest"]["prize_pool"] = 1000
    return bundle


def test_vip_below_standings_limit_emits_numeric_rank_points_and_pmr(monkeypatch, tmp_path) -> None:
    bundle = _collect_vip_below_standings_limit(monkeypatch, tmp_path)
    envelope = build_snapshot_v3_envelope(
        {"NBA": 321}, generated_at="2026-10-04T12:00:00Z", collector=lambda **_: bundle
    )
    contest = envelope["sports"]["nba"]["contests"][0]

    assert [row["entry_key"] for row in contest["standings"]] == ["e0"]
    (vip,) = contest["vip_lineups"]
    assert (vip["rank"], vip["points"], vip["pmr"]) == (879, 28.64, 390.0)
    assert type(vip["rank"]) is int
    assert [row["entry_key"] for row in contest["metrics"]["distance_to_cash"]["per_vip"]] == ["e1"]


def test_vip_lineup_player_names_are_trimmed(monkeypatch, tmp_path) -> None:
    bundle = _collect_vip_below_standings_limit(monkeypatch, tmp_path)

    names = [slot["player_name"] for slot in bundle["vip_lineups"][0]["players_live"]]
    assert names == ["Rams", "Player B", "LOCKED 🔒"]


@pytest.mark.parametrize(
    ("rank", "pts", "pmr"),
    [("", None, "n/a"), (None, "", None)],
)
def test_unparseable_vip_figures_are_omitted_not_null(monkeypatch, tmp_path, rank, pts, pmr) -> None:
    lineup = _typed_vip_lineup()
    lineup.rank, lineup.pts, lineup.pmr = rank, pts, pmr
    vip = _collect_typed_vip_bundle(monkeypatch, tmp_path, lineup=lineup)["vip_lineups"][0]

    assert not {"rank", "points", "pmr", "pts"} & vip.keys()
