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
    assert raw["vip_lineups"] == [{"entry_key": "e1"}]
    assert raw["train_clusters"] == [{"cluster_id": "c1", "entry_keys": ["e1"]}]


def test_collect_raw_bundle_filters_vips_and_trains_to_selected_entry_keys(monkeypatch) -> None:
    monkeypatch.setattr(
        "dk_results.services.snapshot_v3.collector.collect_snapshot_data",
        lambda **_kwargs: {
            "sport": "NBA",
            "contest": {"contest_id": "123", "name": "Contest"},
            "selection": {"selected_contest_id": "123", "reason": {"mode": "explicit_id"}},
            "standings": [{"entry_key": "e1"}, {"entry_key": "e2"}],
            "vip_lineups": [
                {"entry_key": "e1", "display_name": "keep"},
                {"entry_key": "x9", "display_name": "drop"},
                {"display_name": "drop-missing"},
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

    assert raw["vip_lineups"] == [{"entry_key": "e1", "display_name": "keep"}]
    assert raw["train_clusters"] == [{"cluster_id": "c1", "entry_keys": ["e1"]}]
