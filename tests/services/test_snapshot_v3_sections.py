"""Focused unit tests for the pure snapshot-v3 section builders."""

from types import SimpleNamespace

from dk_results.services.snapshot_v3 import sections


def _user(**kwargs):
    base = dict(rank=None, pts=None, pmr=None, player_id=None, name=None, salary=0, lineupobj=None)
    base.update(kwargs)
    return SimpleNamespace(**base)


def _player(**kwargs):
    base = dict(
        name="",
        pos="",
        roster_pos=(),
        salary=0,
        team_abbv="",
        game_info="",
        matchup_info="",
        ownership=0.0,
        fpts=0.0,
        value=0.0,
    )
    base.update(kwargs)
    return SimpleNamespace(**base)


def _results(**kwargs):
    base = dict(
        users=[],
        players={},
        min_rank=0,
        min_cash_pts=0.0,
        non_cashing_users=0,
        non_cashing_players={},
        non_cashing_avg_pmr=None,
    )
    base.update(kwargs)
    return SimpleNamespace(**base)


def test_build_standings_rows_sorts_by_rank_and_marks_points_cashing() -> None:
    results = _results(
        min_rank=1,
        min_cash_pts=100.0,
        users=[
            _user(rank="2", pts="90", pmr="0", player_id="e2", name="below"),
            _user(rank="1", pts="120", pmr="10", player_id="e1", name="above"),
        ],
    )

    rows = sections.build_standings_rows(
        results,
        leaderboard_payout_by_entry={},
        vip_lookup=set(),
        vip_points_by_entry={},
    )

    assert [row["entry_key"] for row in rows] == ["e1", "e2"]
    assert rows[0]["is_cashing"] is True  # 120 >= 100 cutoff
    assert rows[1]["is_cashing"] is False  # 90 < 100 cutoff
    assert rows[0]["rank"] == 1  # numeric-parsed


def test_build_standings_rows_payout_cents_drives_cashing_over_points() -> None:
    # No points cutoff (min_rank == 0), so payout_cents decides cashing.
    results = _results(users=[_user(rank="5", pts="10", pmr="0", player_id="e1", name="paid")])

    rows = sections.build_standings_rows(
        results,
        leaderboard_payout_by_entry={"e1": 250},
        vip_lookup=set(),
        vip_points_by_entry={},
    )

    assert rows[0]["payout_cents"] == 250
    assert rows[0]["is_cashing"] is True


def test_build_players_sorts_by_position_then_name_then_salary() -> None:
    results = _results(
        players={
            "b": _player(name="Bravo", pos="PG", salary=7000, ownership=0.25),
            "a": _player(name="Alpha", pos="PG", salary=5000, ownership=0.10),
            "c": _player(name="Charlie", pos="SG", salary=6000, ownership=0.30),
        }
    )

    players = sections.build_players(results)

    assert [p["name"] for p in players] == ["Alpha", "Bravo", "Charlie"]
    assert players[0]["ownership_pct"] == 10.0  # 0.10 * 100


def test_build_top_remaining_players_percentages_and_cap() -> None:
    results = _results(
        non_cashing_users=4,
        non_cashing_players={f"P{i}": i for i in range(1, 13)},
    )

    top = sections.build_top_remaining_players(results)

    assert len(top) == 10  # capped
    # highest count first: P12 -> 12/4 * 100 = 300
    assert top[0] == {"player_name": "P12", "ownership_remaining_pct": 300.0}


def test_build_top_remaining_players_empty_when_no_non_cashing_users() -> None:
    assert sections.build_top_remaining_players(_results(non_cashing_users=0)) == []


def test_build_watchlist_orders_by_remaining_ownership_and_skips_non_numeric() -> None:
    full_standings = [
        {"entry_key": "e1", "username": "low", "ownership_remaining_total_pct": 10.0, "rank": 3, "points": 1, "pmr": 1},
        {
            "entry_key": "e2",
            "username": "high",
            "ownership_remaining_total_pct": 90.0,
            "rank": 1,
            "points": 2,
            "pmr": 2,
        },
        {
            "entry_key": "e3",
            "username": "none",
            "ownership_remaining_total_pct": None,
            "rank": 2,
            "points": 3,
            "pmr": 3,
        },
    ]

    watchlist = sections.build_watchlist(full_standings)

    assert [row["entry_key"] for row in watchlist] == ["e2", "e1"]  # e3 skipped (non-numeric)
    assert watchlist[0]["display_name"] == "high"


def test_build_cash_line_computes_delta_to_first_below_cutoff() -> None:
    results = _results(min_rank=1, min_cash_pts=100.0)
    full_standings = [
        {"rank": 1, "points": 120.0},
        {"rank": 2, "points": 95.0},  # first below the cash rank
    ]

    cash_line = sections.build_cash_line(results, full_standings)

    assert cash_line["rank"] == 1
    assert cash_line["points"] == 100.0
    assert cash_line["delta_to_cash"] == -5.0  # 95 - 100
    assert cash_line["cutoff_type"] == "positions_paid"


def test_build_cash_line_none_when_min_rank_zero() -> None:
    cash_line = sections.build_cash_line(_results(min_rank=0), [{"rank": 1, "points": 5.0}])
    assert cash_line["rank"] is None
    assert cash_line["points"] is None
    assert cash_line["delta_to_cash"] is None


def test_build_train_clusters_groups_shared_lineups_and_drops_singletons() -> None:
    results = _results(
        users=[
            _user(rank=1, pts=100, pmr=5, player_id="e1", name="a", salary=30000),
            _user(rank=2, pts=100, pmr=5, player_id="e2", name="b", salary=25000),  # same pts/pmr -> cluster
            _user(rank=3, pts=50, pmr=5, player_id="e3", name="c", salary=20000),  # singleton -> dropped
        ]
    )

    clusters = sections.build_train_clusters(results)

    assert len(clusters) == 1
    assert clusters[0]["user_count"] == 2
    assert clusters[0]["entry_keys"] == ["e1", "e2"]
    assert clusters[0]["points"] == 100.0


def test_build_train_clusters_ignores_users_above_salary_limit() -> None:
    results = _results(
        users=[
            _user(rank=1, pts=100, pmr=5, player_id="e1", name="a", salary=45000),
            _user(rank=2, pts=100, pmr=5, player_id="e2", name="b", salary=48000),
        ]
    )

    assert sections.build_train_clusters(results) == []
