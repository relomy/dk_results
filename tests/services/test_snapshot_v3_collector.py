from dk_results.services.snapshot_v3.collector import collect_raw_bundle


def test_collect_raw_bundle_returns_expected_raw_shape(monkeypatch) -> None:
    monkeypatch.setattr(
        "dk_results.services.snapshot_v3.collector.collect_snapshot_data",
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
        "dk_results.services.snapshot_v3.collector.collect_snapshot_data",
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
            "players_live": [{"player_name": "A", "is_live": False}],
        },
    ]
    assert raw["train_clusters"] == [
        {"cluster_id": "c1", "entry_keys": ["e1", "x9"]},
        {"cluster_id": "c2", "entry_keys": ["x9"]},
    ]


def test_collect_raw_bundle_marks_textual_live_status_as_live(monkeypatch) -> None:
    monkeypatch.setattr(
        "dk_results.services.snapshot_v3.collector.collect_snapshot_data",
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
