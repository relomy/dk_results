import json
from argparse import Namespace

import commands.export_fixture as export_command

import dk_results.cli.export_fixture as export_fixture
from dk_results.services.json_stable import to_stable_json


def _canonical_contest_seed(*, contest_id: int | str, name: str = "Contest", sport: str = "nba") -> dict:
    return {
        "contest_id": contest_id,
        "name": name,
        "sport": sport,
        "contest_type": "classic",
        "start_time": "2026-02-14T10:00:00Z",
        "state": "live",
        "entry_fee_cents": 1000,
        "prize_pool_cents": 250000,
        "currency": "USD",
        "max_entries": 1000,
        "max_entries_per_user": 1,
        "is_primary": True,
    }


def test_cli_export_fixture_calls_snapshot_v3_envelope_builder(monkeypatch, tmp_path):
    called = {}

    def fake_build_snapshot_v3_envelope(selected_contests, *, standings_limit, generated_at=None):
        called["selected_contests"] = selected_contests
        called["standings_limit"] = standings_limit
        called["generated_at"] = generated_at
        return {
            "schema_version": 3,
            "snapshot_at": "2026-02-14T10:00:00Z",
            "generated_at": "2026-02-14T10:00:00Z",
            "sports": {
                "nba": {
                    "status": "ok",
                    "updated_at": "2026-02-14T10:00:00Z",
                    "players": [],
                    "primary_contest": {
                        "contest_id": "1",
                        "contest_key": "nba:1",
                        "selection_reason": {"mode": "explicit_id"},
                        "selected_at": "2026-02-14T10:00:00Z",
                    },
                    "contests": [],
                }
            },
        }

    monkeypatch.setattr(export_command, "build_snapshot_v3_envelope", fake_build_snapshot_v3_envelope)
    args = Namespace(
        sport="nba",
        contest_id=None,
        out=str(tmp_path / "snapshot.json"),
        standings_limit=500,
    )
    rc = export_command.run_export_fixture(args)

    assert rc == 0
    assert called["selected_contests"] == {"NBA": None}
    assert called["standings_limit"] == 500


def test_cli_export_fixture_defaults_out_path_when_missing(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(export_command, "configure_runtime", lambda: None)
    monkeypatch.setattr(
        export_command,
        "build_snapshot_v3_envelope",
        lambda *_args, **_kwargs: {
            "schema_version": 3,
            "snapshot_at": "2026-02-14T10:00:00Z",
            "generated_at": "2026-02-14T10:00:00Z",
            "sports": {
                "nba": {
                    "status": "ok",
                    "updated_at": "2026-02-14T10:00:00Z",
                    "players": [],
                    "primary_contest": {
                        "contest_id": "42",
                        "contest_key": "nba:42",
                        "selection_reason": {"mode": "explicit_id"},
                        "selected_at": "2026-02-14T10:00:00Z",
                    },
                    "contests": [],
                }
            },
        },
    )
    args = Namespace(
        sport="nba",
        contest_id=None,
        out=None,
        standings_limit=500,
    )

    rc = export_command.run_export_fixture(args)
    assert rc == 0
    assert (tmp_path / "fixtures" / "nba-42-fixture.json").exists()


def test_standalone_main_routes_export_fixture(monkeypatch, tmp_path):
    called = {}

    def fake_run(args):
        called["sport"] = args.sport
        called["out"] = args.out
        return 0

    monkeypatch.setattr(export_fixture, "run_export_fixture", fake_run)
    rc = export_fixture.main(
        [
            "--sport",
            "NBA",
            "--out",
            str(tmp_path / "out.json"),
        ]
    )
    assert rc == 0
    assert called["sport"] == "NBA"


def test_standalone_main_bundle_routes_export_bundle(monkeypatch, tmp_path):
    called = {}

    def fake_bundle(args):
        called["items"] = list(args.item)
        called["out"] = args.out
        return 0

    monkeypatch.setattr(export_fixture, "run_export_bundle", fake_bundle)
    rc = export_fixture.main(
        [
            "bundle",
            "--item",
            "NBA:123",
            "--item",
            "GOLF:456",
            "--out",
            str(tmp_path / "bundle.json"),
        ]
    )
    assert rc == 0
    assert called["items"] == ["NBA:123", "GOLF:456"]


def test_standalone_main_bundle_routes_from_sys_argv(monkeypatch, tmp_path):
    called = {}

    def fake_bundle(args):
        called["items"] = list(args.item)
        return 0

    monkeypatch.setattr(export_fixture, "run_export_bundle", fake_bundle)
    monkeypatch.setattr(
        export_fixture.sys,
        "argv",
        [
            "export_fixture.py",
            "bundle",
            "--item",
            "NBA:123",
            "--item",
            "GOLF:456",
            "--out",
            str(tmp_path / "bundle.json"),
        ],
    )
    rc = export_fixture.main()
    assert rc == 0
    assert called["items"] == ["NBA:123", "GOLF:456"]


def test_standalone_main_publish_routes_publish_helper(monkeypatch, tmp_path):
    called = {}

    def fake_publish(args):
        called["snapshot"] = args.snapshot
        called["root"] = args.root
        return 0

    monkeypatch.setattr(export_fixture, "run_publish_snapshot", fake_publish)
    rc = export_fixture.main(
        [
            "publish",
            "--snapshot",
            str(tmp_path / "snapshots" / "live.json"),
            "--root",
            str(tmp_path / "public"),
        ]
    )

    assert rc == 0
    assert called["snapshot"].endswith("live.json")
    assert called["root"].endswith("public")


def test_run_export_bundle_writes_two_sports(monkeypatch, tmp_path):
    monkeypatch.setattr(export_command, "configure_runtime", lambda: None)

    def _fake_build_snapshot_v3_envelope(selected_contests, *, standings_limit, generated_at=None):
        assert selected_contests == {"NBA": 123, "GOLF": 456}
        assert standings_limit == 42
        return {
            "schema_version": 3,
            "snapshot_at": "2026-02-14T10:00:00Z",
            "generated_at": "2026-02-14T10:00:00Z",
            "sports": {
                "nba": {"primary_contest": {"contest_id": "123"}},
                "golf": {"primary_contest": {"contest_id": "456"}},
            },
        }

    monkeypatch.setattr(export_command, "build_snapshot_v3_envelope", _fake_build_snapshot_v3_envelope)
    out = tmp_path / "bundle.json"
    args = Namespace(
        item=["NBA:123", "GOLF:456"],
        out=str(out),
        standings_limit=42,
    )

    rc = export_command.run_export_bundle(args)
    payload = out.read_text(encoding="utf-8")

    assert rc == 0
    assert '"schema_version":3' in payload
    assert '"nba"' in payload
    assert '"golf"' in payload
    assert '"contest_id":"123"' in payload
    assert '"contest_id":"456"' in payload


def test_run_export_bundle_applies_generated_at_override(monkeypatch, tmp_path):
    monkeypatch.setattr(export_command, "configure_runtime", lambda: None)
    called = {}

    def _fake_build_snapshot_v3_envelope(selected_contests, *, standings_limit, generated_at=None):
        called["generated_at"] = generated_at
        return {
            "schema_version": 3,
            "snapshot_at": generated_at,
            "generated_at": generated_at,
            "sports": {"nba": {"primary_contest": {"contest_id": "123"}}},
        }

    monkeypatch.setattr(export_command, "build_snapshot_v3_envelope", _fake_build_snapshot_v3_envelope)
    out = tmp_path / "bundle-generated-at.json"
    args = Namespace(
        item=["NBA:123"],
        out=str(out),
        standings_limit=42,
        generated_at="2026-02-25T11:22:33.999+00:00",
    )

    rc = export_command.run_export_bundle(args)
    payload = json.loads(out.read_text(encoding="utf-8"))

    assert rc == 0
    assert called["generated_at"] == "2026-02-25T11:22:33.999+00:00"
    assert payload["generated_at"] == "2026-02-25T11:22:33Z"


def test_run_export_fixture_applies_generated_at_override(monkeypatch, tmp_path):
    monkeypatch.setattr(export_command, "configure_runtime", lambda: None)
    called = {}

    monkeypatch.setattr(
        export_command,
        "build_snapshot_v3_envelope",
        lambda *_args, **kwargs: (
            called.update({"generated_at": kwargs.get("generated_at")})
            or {
                "schema_version": 3,
                "snapshot_at": kwargs.get("generated_at"),
                "generated_at": kwargs.get("generated_at"),
                "sports": {"nba": {"primary_contest": {"contest_id": "123"}}},
            }
        ),
    )
    out = tmp_path / "fixture-generated-at.json"
    args = Namespace(
        sport="NBA",
        contest_id=123,
        out=str(out),
        standings_limit=42,
        generated_at="2026-02-25T11:22:33.999+00:00",
    )

    rc = export_command.run_export_fixture(args)
    payload = json.loads(out.read_text(encoding="utf-8"))

    assert rc == 0
    assert called["generated_at"] == "2026-02-25T11:22:33.999+00:00"
    assert payload["generated_at"] == "2026-02-25T11:22:33Z"


def test_run_export_fixture_emits_envelope_and_contract_sections(monkeypatch, tmp_path):
    monkeypatch.setattr(export_command, "configure_runtime", lambda: None)
    monkeypatch.setattr(
        export_command,
        "build_snapshot_v3_envelope",
        lambda *_args, **_kwargs: {
            "schema_version": 3,
            "snapshot_at": "2026-02-14T10:00:00Z",
            "generated_at": "2026-02-14T10:00:00Z",
            "sports": {
                "nba": {
                    "status": "ok",
                    "updated_at": "2026-02-14T10:00:00Z",
                    "players": [{"name": "A"}, {"name": "B"}],
                    "primary_contest": {
                        "contest_id": "188080404",
                        "contest_key": "nba:188080404",
                        "selection_reason": {"mode": "explicit_id"},
                        "selected_at": "2026-02-14T10:00:00Z",
                    },
                    "contests": [
                        {
                            **_canonical_contest_seed(contest_id="188080404", name="NBA Single Entry", sport="nba"),
                            "contest_key": "nba:188080404",
                        }
                    ],
                }
            },
        },
    )

    out = tmp_path / "single-envelope.json"
    rc = export_command.run_export_fixture(
        Namespace(
            sport="NBA",
            contest_id=188080404,
            out=str(out),
            standings_limit=100,
        )
    )

    payload = json.loads(out.read_text(encoding="utf-8"))
    sport = payload["sports"]["nba"]
    contest = sport["contests"][0]

    assert rc == 0
    assert payload["schema_version"] == 3
    assert payload["generated_at"].endswith("Z")
    assert payload["snapshot_at"].endswith("Z")
    assert set(sport.keys()) == {
        "status",
        "updated_at",
        "primary_contest",
        "players",
        "contests",
    }
    assert sport["status"] == "ok"
    assert sport["primary_contest"]["contest_id"] == "188080404"
    assert isinstance(sport["primary_contest"]["selection_reason"], dict)
    assert contest["contest_id"] == "188080404"
    required_canonical_fields = {
        "contest_id": str,
        "contest_key": str,
        "name": str,
        "sport": str,
        "contest_type": str,
        "start_time": str,
        "state": str,
        "entry_fee_cents": int,
        "prize_pool_cents": int,
        "currency": str,
        "max_entries": int,
        "max_entries_per_user": int,
    }
    for field_name, expected_type in required_canonical_fields.items():
        assert field_name in contest
        assert contest[field_name] is not None
        assert type(contest[field_name]) is expected_type
    assert contest["entry_fee_cents"] == 1000
    assert sport["primary_contest"]["contest_key"] == contest["contest_key"]


def test_run_export_bundle_emits_contests_primary_contest_and_players(monkeypatch, tmp_path):
    monkeypatch.setattr(export_command, "configure_runtime", lambda: None)

    def _fake_build_snapshot_v3_envelope(_selected_contests, *, standings_limit, generated_at=None):
        return {
            "schema_version": 3,
            "snapshot_at": "2026-02-14T10:00:00Z",
            "generated_at": "2026-02-14T10:00:00Z",
            "sports": {
                "nba": {
                    "status": "ok",
                    "updated_at": "2026-02-14T10:00:00Z",
                    "players": [{"name": "Player One"}],
                    "primary_contest": {"contest_id": "123", "contest_key": "nba:123"},
                    "contests": [
                        {
                            **_canonical_contest_seed(contest_id="123", name="NBA contest", sport="nba"),
                            "contest_key": "nba:123",
                        }
                    ],
                },
                "golf": {
                    "status": "ok",
                    "updated_at": "2026-02-14T10:00:00Z",
                    "players": [],
                    "primary_contest": {"contest_id": "456", "contest_key": "golf:456"},
                    "contests": [
                        {
                            **_canonical_contest_seed(contest_id="456", name="GOLF contest", sport="golf"),
                            "contest_key": "golf:456",
                        }
                    ],
                },
            },
        }

    monkeypatch.setattr(export_command, "build_snapshot_v3_envelope", _fake_build_snapshot_v3_envelope)

    out = tmp_path / "bundle-contract.json"
    rc = export_command.run_export_bundle(
        Namespace(
            item=["NBA:123", "GOLF:456"],
            out=str(out),
            standings_limit=42,
        )
    )
    payload = json.loads(out.read_text(encoding="utf-8"))

    assert rc == 0
    assert payload["schema_version"] == 3
    assert sorted(payload["sports"].keys()) == ["golf", "nba"]
    assert payload["sports"]["nba"]["primary_contest"]["contest_id"] == "123"
    assert payload["sports"]["golf"]["contests"][0]["contest_id"] == "456"
    assert payload["sports"]["nba"]["players"][0]["name"] == "Player One"


def test_run_publish_snapshot_writes_latest_and_manifest(tmp_path):
    root = tmp_path / "public"
    snapshot_file = root / "snapshots" / "live-1.json"
    snapshot_file.parent.mkdir(parents=True, exist_ok=True)
    snapshot_file.write_text(
        to_stable_json(
            {
                "schema_version": 3,
                "snapshot_at": "2026-02-15T01:30:00Z",
                "generated_at": "2026-02-15T01:30:05Z",
                "sports": {
                    "nba": {
                        "status": "ok",
                        "updated_at": "2026-02-15T01:30:00Z",
                        "contests": [{"state": "live"}, {"state": "completed"}],
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    args = Namespace(
        snapshot=str(snapshot_file),
        root=str(root),
        snapshot_path=None,
        latest_out=None,
        manifest_dir=None,
    )
    rc = export_command.run_publish_snapshot(args)

    latest = json.loads((root / "latest.json").read_text(encoding="utf-8"))
    manifest = json.loads((root / "manifest" / "2026-02-15.json").read_text(encoding="utf-8"))

    assert rc == 0
    assert latest["latest_snapshot_path"] == "snapshots/live-1.json"
    assert latest["manifest_today_path"] == "manifest/2026-02-15.json"
    assert latest["manifest_yesterday_path"] == "manifest/2026-02-14.json"
    assert latest["available_sports"] == ["nba"]
    assert manifest["manifest_version"] == 1
    assert manifest["date_utc"] == "2026-02-15"
    assert len(manifest["snapshots"]) == 1
    entry = manifest["snapshots"][0]
    assert entry["snapshot_at"] == "2026-02-15T01:30:00Z"
    assert entry["path"] == "snapshots/live-1.json"
    assert entry["sports_present"] == ["nba"]
    assert entry["contest_counts_by_sport"] == {"nba": 2}
    assert entry["state_counts"] == {"completed": 1, "live": 1}
    assert entry["sports_status"]["nba"]["status"] == "ok"

    rc_second = export_command.run_publish_snapshot(args)
    manifest_second = json.loads((root / "manifest" / "2026-02-15.json").read_text(encoding="utf-8"))
    assert rc_second == 0
    assert len(manifest_second["snapshots"]) == 1


def _fixture_export_v3_envelope(*, vip_lineups=None, standings=None):
    return {
        "schema_version": 3,
        "snapshot_at": "2026-02-14T10:00:00Z",
        "generated_at": "2026-02-14T10:00:00Z",
        "sports": {
            "nba": {
                "status": "ok",
                "updated_at": "2026-02-14T10:00:00Z",
                "players": [],
                "primary_contest": {
                    "contest_id": "1",
                    "contest_key": "nba:1",
                    "selection_reason": {"mode": "explicit_id"},
                    "selected_at": "2026-02-14T10:00:00Z",
                },
                "contests": [
                    {
                        **_canonical_contest_seed(contest_id="1", name="NBA contest", sport="nba"),
                        "contest_key": "nba:1",
                        "vip_lineups": vip_lineups or [],
                        "standings": standings or [],
                    }
                ],
            }
        },
    }


def test_vip_lineups_support_user_and_players_shape(monkeypatch, tmp_path):
    monkeypatch.setattr(export_command, "configure_runtime", lambda: None)
    monkeypatch.setattr(
        export_command,
        "build_snapshot_v3_envelope",
        lambda *_args, **_kwargs: _fixture_export_v3_envelope(
            vip_lineups=[
                {
                    "display_name": "vip_user",
                    "entry_key": "777",
                    "slots": [{"slot": "PG", "player_name": "Alpha"}, {"slot": "SG", "player_name": "Beta"}],
                    "live": {
                        "current_rank": 5,
                        "pmr": 0.0,
                        "is_cashing": True,
                        "payout_cents": 1500,
                    },
                }
            ]
        ),
    )
    out = tmp_path / "vip-shape.json"
    rc = export_command.run_export_fixture(Namespace(sport="NBA", contest_id=1, out=str(out), standings_limit=100))
    payload = json.loads(out.read_text(encoding="utf-8"))
    vip = payload["sports"]["nba"]["contests"][0]["vip_lineups"][0]

    assert rc == 0
    assert vip["display_name"] == "vip_user"
    assert vip["entry_key"] == "777"
    assert vip["slots"][0]["slot"] == "PG"
    assert vip["slots"][0]["player_name"] == "Alpha"
    assert vip["slots"][1]["slot"] == "SG"
    assert vip["slots"][1]["player_name"] == "Beta"
    assert isinstance(vip["live"]["pmr"], float)
    assert isinstance(vip["live"]["current_rank"], int)
    assert vip["live"]["is_cashing"] is True
    assert vip["live"]["payout_cents"] == 1500


def test_vip_lineups_export_players_live_typed_fields(monkeypatch, tmp_path):
    monkeypatch.setattr(export_command, "configure_runtime", lambda: None)
    monkeypatch.setattr(
        export_command,
        "build_snapshot_v3_envelope",
        lambda *_args, **_kwargs: _fixture_export_v3_envelope(
            vip_lineups=[
                {
                    "display_name": "vip_user",
                    "entry_key": "777",
                    "players_live": [
                        {
                            "slot": "PG",
                            "player_name": "Javon Small",
                            "game_status": "In Progress",
                            "ownership_pct": 84.67,
                            "salary": 3500,
                            "points": 7.25,
                            "value": 2.07,
                            "rt_projection": 21.11,
                            "time_remaining_display": "38.02",
                            "time_remaining_minutes": 38.02,
                            "stats_text": "1 REB, 1 STL, 4 PTS",
                        },
                        {
                            "slot": "C",
                            "player_name": "LOCKED 🔒",
                        },
                    ],
                }
            ]
        ),
    )
    out = tmp_path / "vip-players-live.json"
    rc = export_command.run_export_fixture(Namespace(sport="NBA", contest_id=1, out=str(out), standings_limit=100))
    payload = json.loads(out.read_text(encoding="utf-8"))
    vip = payload["sports"]["nba"]["contests"][0]["vip_lineups"][0]

    assert rc == 0
    assert len(vip["players_live"]) == 2
    row0 = vip["players_live"][0]
    assert row0["slot"] == "PG"
    assert row0["player_name"] == "Javon Small"
    assert row0["game_status"] == "In Progress"
    assert row0["ownership_pct"] == 84.67
    assert row0["salary"] == 3500
    assert row0["points"] == 7.25
    assert row0["value"] == 2.07
    assert row0["rt_projection"] == 21.11
    assert row0["time_remaining_display"] == "38.02"
    assert row0["time_remaining_minutes"] == 38.02
    assert row0["stats_text"] == "1 REB, 1 STL, 4 PTS"

    row1 = vip["players_live"][1]
    assert row1["slot"] == "C"
    assert row1["player_name"] == "LOCKED 🔒"
    assert "game_status" not in row1
    assert "ownership_pct" not in row1


def test_export_fixture_preserves_missing_vip_entry_key(monkeypatch, tmp_path):
    monkeypatch.setattr(export_command, "configure_runtime", lambda: None)
    monkeypatch.setattr(
        export_command,
        "build_snapshot_v3_envelope",
        lambda *_args, **_kwargs: _fixture_export_v3_envelope(
            vip_lineups=[
                {
                    "display_name": "dup_user",
                    "entry_key": None,
                    "slots": [{"slot": "PG", "player_name": "Alpha"}],
                }
            ]
        ),
    )
    out = tmp_path / "vip-ambiguous.json"
    rc = export_command.run_export_fixture(Namespace(sport="NBA", contest_id=1, out=str(out), standings_limit=100))
    payload = json.loads(out.read_text(encoding="utf-8"))
    vip = payload["sports"]["nba"]["contests"][0]["vip_lineups"][0]

    assert rc == 0
    assert vip["entry_key"] is None


def test_standings_is_cashing_derived_from_payout_presence(monkeypatch, tmp_path):
    monkeypatch.setattr(export_command, "configure_runtime", lambda: None)
    monkeypatch.setattr(
        export_command,
        "build_snapshot_v3_envelope",
        lambda *_args, **_kwargs: _fixture_export_v3_envelope(
            standings=[
                {
                    "entry_key": "a",
                    "username": "u1",
                    "rank": 1,
                    "points": 120.0,
                    "pmr": 0.0,
                    "payout_cents": 2500,
                    "is_cashing": True,
                },
                {
                    "entry_key": "b",
                    "username": "u2",
                    "rank": 40,
                    "points": 90.0,
                    "pmr": 2.0,
                    "payout_cents": None,
                    "is_cashing": False,
                },
            ]
        ),
    )
    out = tmp_path / "cashing-rule.json"
    rc = export_command.run_export_fixture(Namespace(sport="NBA", contest_id=1, out=str(out), standings_limit=100))
    payload = json.loads(out.read_text(encoding="utf-8"))
    rows = payload["sports"]["nba"]["contests"][0]["standings"]

    assert rc == 0
    assert rows[0]["payout_cents"] == 2500
    assert rows[0]["is_cashing"] is True
    assert rows[1]["payout_cents"] is None
    assert rows[1]["is_cashing"] is False
