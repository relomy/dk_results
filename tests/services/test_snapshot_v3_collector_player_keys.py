"""collect_raw_bundle's player-key and VIP-row normalization over malformed and ambiguous input."""

from dk_results.services.snapshot_v3.collector import collect_raw_bundle


def _raw(**sections):
    base = {
        "sport": "NBA",
        "contest": {"contest_id": "123"},
        "selection": {"selected_contest_id": "123"},
        "standings": [],
        "vip_lineups": [],
        "train_clusters": [],
        "players": [],
        "cash_line": {},
        "ownership": {},
        "metadata": {},
        "truncation": {},
        "candidates": [],
    }
    return {**base, **sections}


def _bundle(monkeypatch, **sections):
    raw = _raw(**sections)
    monkeypatch.setattr("dk_results.services.snapshot_v3.collector._collect_source_snapshot", lambda **_kwargs: raw)
    return collect_raw_bundle(sport="NBA", contest_id=123, standings_limit=10)


def test_players_drop_non_dicts_trim_names_and_key_only_named_rows(monkeypatch) -> None:
    players = [
        "not-a-row",
        {"name": " Al Ho ", "team": "BOS", "position": "PG", "salary": 5000.4},
        {"name": "Bo", "player_key": 123},
        {"salary": 1},
    ]

    bundle = _bundle(monkeypatch, players=players)

    assert bundle["players"] == [
        {"name": "Al Ho", "team": "BOS", "position": "PG", "salary": 5000.4, "player_key": "nba:al-ho:bos:5000:pg"},
        {"name": "Bo", "player_key": "123"},
        {"salary": 1},
    ]


def test_ambiguous_player_name_never_backfills_a_vip_slot_key(monkeypatch) -> None:
    players = [{"name": "Dup", "player_key": "k1"}, {"name": "Dup", "player_key": "k2"}]
    vip_lineups = [{"entry_key": "e1", "players": [{"name": "Dup", "pos": "PG", "salary": 5000}]}]

    bundle = _bundle(monkeypatch, players=players, vip_lineups=vip_lineups)

    assert bundle["vip_lineups"][0]["players_live"] == [
        {"slot": "PG", "player_name": "Dup", "player_key": "nba:dup:na:5000:pg", "salary": 5000, "is_live": False}
    ]


def test_conflicting_vip_slot_key_drops_the_name_from_top_remaining_backfill(monkeypatch) -> None:
    players = [{"name": "Al", "player_key": "k1"}, {"name": "Bo", "player_key": "k2"}]
    vip_lineups = [{"entry_key": "e1", "players": [{"name": "Al", "pos": "PG", "player_key": "k9"}]}]
    top = ["not-a-row", {"player_name": "Al"}, {"player_name": " Bo "}, {"player_name": "Cy", "player_key": 7}]

    bundle = _bundle(
        monkeypatch,
        players=players,
        vip_lineups=vip_lineups,
        ownership={"top_remaining_players": top, "non_cashing_top_remaining_players": "not-a-list"},
    )

    assert bundle["vip_lineups"][0]["players_live"][0]["player_key"] == "k9"
    assert bundle["ownership"]["top_remaining_players"] == [
        {"player_name": "Al"},
        {"player_name": "Bo", "player_key": "k2"},
        {"player_name": "Cy", "player_key": "7"},
    ]
    assert bundle["ownership"]["non_cashing_top_remaining_players"] == "not-a-list"


def test_vip_rows_drop_non_dicts_and_unnamed_slots_and_skip_malformed_standings(monkeypatch) -> None:
    vip_lineups = [
        "not-a-row",
        {"display_name": "Vee", "players": ["not-a-slot", {"name": "  "}, {"name": "Cy", "pos": "F"}]},
    ]
    standings = ["not-a-row", {"username": " vee ", "entry_key": "e5"}]

    bundle = _bundle(monkeypatch, vip_lineups=vip_lineups, standings=standings)

    assert bundle["vip_lineups"] == [
        {
            "display_name": "Vee",
            "entry_key": "e5",
            "vip_entry_key": "e5",
            "players_live": [{"slot": "F", "player_name": "Cy", "player_key": "nba:cy:na:na:f", "is_live": False}],
        }
    ]
