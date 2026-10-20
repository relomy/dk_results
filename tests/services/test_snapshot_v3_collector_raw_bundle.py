"""collect_raw_bundle: the raw bundle shape and its VIP name-to-player-key mapping."""

from dk_results.services.snapshot_v3.collector import (
    _build_unique_name_to_player_key_from_vip_lineups,
    collect_raw_bundle,
)
from dk_results.services.snapshot_v3.derive import derive_threat


def test_build_unique_name_to_player_key_maps_single_source() -> None:
    vip_lineups = [{"players_live": [{"player_name": "Player A", "player_key": "nba:1"}]}]
    assert _build_unique_name_to_player_key_from_vip_lineups(vip_lineups) == {"player a": "nba:1"}


def test_build_unique_name_to_player_key_drops_ambiguous_name() -> None:
    vip_lineups = [
        {"players_live": [{"player_name": "Player A", "player_key": "nba:1"}]},
        {"players_live": [{"player_name": "Player A", "player_key": "nba:2"}]},
    ]
    assert _build_unique_name_to_player_key_from_vip_lineups(vip_lineups) == {}


def test_build_unique_name_to_player_key_skips_non_list_players_live() -> None:
    vip_lineups = [{"players_live": "not-a-list"}, "not-a-dict"]
    assert _build_unique_name_to_player_key_from_vip_lineups(vip_lineups) == {}


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
                {"user": "vip-without-key", "players": [{"name": "A", "pos": "UTIL"}]},
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
            "players_live": [{"slot": "UTIL", "player_name": "A", "player_key": "nba:a:na:na:util", "is_live": False}],
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
                {"user": "dup-user", "players": [{"name": "A", "pos": "UTIL"}]},
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
            "players_live": [{"slot": "UTIL", "player_name": "A", "player_key": "nba:a:na:na:util", "is_live": False}],
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
    assert threat is None  # an empty player pool has no Game status


def test_collect_raw_bundle_trims_player_names_in_players_and_top_remaining(monkeypatch) -> None:
    monkeypatch.setattr(
        "dk_results.services.snapshot_v3.collector._collect_source_snapshot",
        lambda **_kwargs: {
            "sport": "NFL",
            "contest": {"contest_id": "123", "name": "Contest"},
            "selection": {"selected_contest_id": "123", "reason": {"mode": "explicit_id"}},
            "standings": [],
            "vip_lineups": [],
            "train_clusters": [],
            "players": [{"name": "Rams ", "position": "DST", "salary": 3000, "team": "LAR"}],
            "cash_line": {},
            "ownership": {
                "top_remaining_players": [{"player_name": "Rams ", "ownership_remaining_pct": 40.0}],
                "non_cashing_top_remaining_players": [{"player_name": "Jets ", "ownership_remaining_pct": 30.0}],
            },
            "metadata": {},
            "truncation": {},
            "candidates": [],
        },
    )

    raw = collect_raw_bundle(sport="NFL", contest_id=123, standings_limit=10)

    assert [row["name"] for row in raw["players"]] == ["Rams"]
    assert [row["player_name"] for row in raw["ownership"]["top_remaining_players"]] == ["Rams"]
    assert [row["player_name"] for row in raw["ownership"]["non_cashing_top_remaining_players"]] == ["Jets"]
