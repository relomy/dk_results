from dk_results.services.snapshot_v3.pipeline import build_snapshot_v3_envelope


def test_build_snapshot_v3_envelope_normalizes_generated_at_and_orders_sports(monkeypatch) -> None:
    build_calls: list[tuple[str, str]] = []

    monkeypatch.setattr(
        "dk_results.services.snapshot_v3.pipeline.collect_snapshot",
        lambda *, sport, contest_id, standings_limit: {
            "sport": sport,
            "contest": {"contest_id": str(contest_id or sport)},
        },
    )

    def _fake_build_sport_payload(raw_bundle, *, derived, generated_at):
        build_calls.append((str(raw_bundle["sport"]), generated_at))
        return {
            "status": "ok",
            "updated_at": generated_at,
            "players": [],
            "primary_contest": {
                "contest_id": str(raw_bundle["contest"]["contest_id"]),
                "contest_key": f"{str(raw_bundle['sport']).lower()}:{raw_bundle['contest']['contest_id']}",
                "selection_reason": {"mode": "explicit_id"},
                "selected_at": generated_at,
            },
            "contests": [
                {
                    "contest_id": str(raw_bundle["contest"]["contest_id"]),
                    "contest_key": f"{str(raw_bundle['sport']).lower()}:{raw_bundle['contest']['contest_id']}",
                    "name": f"{raw_bundle['sport']} Contest",
                    "sport": str(raw_bundle["sport"]).lower(),
                    "contest_type": "classic",
                    "start_time": generated_at,
                    "state": "live",
                    "entry_fee_cents": 1000,
                    "prize_pool_cents": 100000,
                    "currency": "USD",
                    "max_entries": 100,
                }
            ],
        }

    monkeypatch.setattr("dk_results.services.snapshot_v3.pipeline.build_sport_payload", _fake_build_sport_payload)
    monkeypatch.setattr("dk_results.services.snapshot_v3.pipeline.validate_v3_envelope", lambda payload: [])

    envelope = build_snapshot_v3_envelope(
        {"NBA": 188080404, "GOLF": 187937165},
        standings_limit=42,
        generated_at="2026-03-01T12:34:56.999+00:00",
    )

    assert envelope["schema_version"] == 3
    assert envelope["snapshot_at"] == "2026-03-01T12:34:56Z"
    assert envelope["generated_at"] == "2026-03-01T12:34:56Z"
    assert list(envelope["sports"].keys()) == ["golf", "nba"]
    assert build_calls == [
        ("GOLF", "2026-03-01T12:34:56Z"),
        ("NBA", "2026-03-01T12:34:56Z"),
    ]


def test_build_snapshot_v3_envelope_raises_on_validation_errors(monkeypatch) -> None:
    monkeypatch.setattr(
        "dk_results.services.snapshot_v3.pipeline.collect_snapshot",
        lambda *, sport, contest_id, standings_limit: {
            "sport": sport,
            "contest": {"contest_id": str(contest_id or "1")},
        },
    )
    monkeypatch.setattr(
        "dk_results.services.snapshot_v3.pipeline.build_sport_payload",
        lambda raw_bundle, *, derived, generated_at: {
            "status": "ok",
            "updated_at": generated_at,
            "players": [],
            "primary_contest": {
                "contest_id": "1",
                "contest_key": "nba:1",
                "selection_reason": {"mode": "explicit_id"},
                "selected_at": generated_at,
            },
            "contests": [],
        },
    )
    monkeypatch.setattr("dk_results.services.snapshot_v3.pipeline.validate_v3_envelope", lambda payload: ["bad"])

    try:
        build_snapshot_v3_envelope({"NBA": 1})
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "Snapshot v3 validation failed: bad" in str(exc)


def _bundle_with_vip_lineup() -> dict:
    """A collected bundle shaped as the collector emits it once typed VIP lineups are converted."""
    return {
        "sport": "NBA",
        "contest": {
            "contest_id": "188080404",
            "name": "NBA Single Entry $10 Double Up",
            "sport": "nba",
            "contest_type": "classic",
            "start_time_utc": "2026-02-15T01:00:00Z",
            "state": "live",
            "entry_fee": 10,
            "prize_pool": 2000,
            "currency": "USD",
            "entries": 229,
            "max_entries_per_user": 1,
        },
        "selected_contest_id": "188080404",
        "selection_reason": {"mode": "explicit_id", "criteria": {"contest_id": "188080404"}},
        "players": [{"name": "Player C", "player_key": "nba:player-c"}],
        "standings": [],
        "train_clusters": [],
        "ownership": {
            "top_remaining_players": [
                {"player_key": "nba:player-a", "player_name": "Player A", "ownership_remaining_pct": 12.5},
                {"player_key": "nba:player-c", "player_name": "Player C", "ownership_remaining_pct": 9.0},
            ]
        },
        "cash_line": {"cutoff_type": "positions_paid", "rank": 60, "points": 250.5},
        "vip_lineups": [
            {
                "display_name": "vipuser",
                "entry_key": "e1",
                "vip_entry_key": "e1",
                "rank": "55",
                "pts": 260.75,
                "pmr": "120",
                "players_live": [
                    {
                        "slot": "PG",
                        "player_name": "Player A",
                        "player_key": "nba:player-a",
                        "salary": 8000,
                        "is_live": True,
                    },
                    {
                        "slot": "SG",
                        "player_name": "Player B",
                        "player_key": "nba:player-b",
                        "salary": 7000,
                        "is_live": False,
                    },
                ],
            }
        ],
    }


def test_build_snapshot_v3_envelope_surfaces_vip_lineups_and_vip_derived_metrics() -> None:
    envelope = build_snapshot_v3_envelope(
        {"NBA": 188080404},
        generated_at="2026-03-01T12:34:56Z",
        collector=lambda *, sport, contest_id, standings_limit: _bundle_with_vip_lineup(),
    )

    contest = envelope["sports"]["nba"]["contests"][0]
    vip = contest["vip_lineups"][0]
    assert (vip["display_name"], vip["entry_key"], vip["rank"], vip["pts"]) == ("vipuser", "e1", "55", 260.75)
    assert [(s["slot"], s["player_key"], s["salary"], s["is_live"]) for s in vip["players_live"]] == [
        ("PG", "nba:player-a", 8000, True),
        ("SG", "nba:player-b", 7000, False),
    ]
    assert contest["metrics"]["distance_to_cash"]["per_vip"] == [
        {
            "vip_entry_key": "e1",
            "entry_key": "e1",
            "display_name": "vipuser",
            "points_delta": 10.25,
            "rank_delta": 5,
        }
    ]
    vip_counts = {row["player_key"]: row["vip_count"] for row in contest["metrics"]["threat"]["top_swing_players"]}
    assert vip_counts == {"nba:player-a": 1, "nba:player-c": 0}
