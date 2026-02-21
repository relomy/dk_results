import datetime
import hashlib
import json
from argparse import Namespace

import commands.export_fixture as export_command
import services.snapshot_exporter as snapshot_exporter

import dk_results.cli.export_fixture as export_fixture


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
        "entries_count": 1000,
        "max_entries": 1000,
        "max_entries_per_user": 1,
        "is_primary": True,
    }


def _valid_envelope_for_validation() -> dict:
    contest = _canonical_contest_seed(contest_id="123", name="Contest", sport="nba")
    contest["contest_key"] = "nba:123"
    return {
        "schema_version": 2,
        "snapshot_at": "2026-02-14T00:00:00Z",
        "generated_at": "2026-02-14T00:00:00Z",
        "sports": {
            "nba": {
                "status": "ok",
                "updated_at": "2026-02-14T00:00:00Z",
                "players": [],
                "primary_contest": {
                    "contest_id": "123",
                    "contest_key": "nba:123",
                    "selection_reason": "explicit_id contest_id=123",
                    "selected_at": "2026-02-14T00:00:00Z",
                },
                "contests": [contest],
            }
        },
    }


def test_snapshot_includes_all_major_sections_even_when_null(monkeypatch):
    monkeypatch.setattr(
        snapshot_exporter,
        "collect_snapshot_data",
        lambda **_kwargs: {
            "snapshot_version": "v1",
            "sport": "NBA",
            "contest": {"contest_id": 123, "is_primary": True, "name": None},
            "selection": {"selected_contest_id": 123, "reason": {}},
            "candidates": [],
            "cash_line": {"cutoff_type": "positions_paid"},
            "vip_lineups": [],
            "ownership": {"ownership_remaining_total_pct": None},
            "train_clusters": [],
            "standings": [],
            "truncation": {},
            "metadata": {"warnings": [], "missing_fields": [], "source_endpoints": []},
        },
    )

    snapshot = snapshot_exporter.build_snapshot(sport="NBA")

    assert set(snapshot) == {
        "snapshot_version",
        "snapshot_generated_at_utc",
        "sport",
        "contest",
        "selection",
        "candidates",
        "cash_line",
        "vip_lineups",
        "players",
        "ownership",
        "train_clusters",
        "standings",
        "truncation",
        "metadata",
    }
    assert "name" in snapshot["contest"]
    assert snapshot["contest"]["name"] is None


def test_load_vips_reads_repo_root_vips_yaml(monkeypatch, tmp_path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir(parents=True)
    (repo_root / "vips.yaml").write_text("- vip_one\n- vip_two\n", encoding="utf-8")
    monkeypatch.setattr(snapshot_exporter, "repo_file", lambda *parts: repo_root.joinpath(*parts))

    assert snapshot_exporter.load_vips() == ["vip_one", "vip_two"]


def test_selection_reason_includes_explicit_criteria_and_tie_breakers():
    reason = snapshot_exporter.build_selection_reason(
        mode="primary_live",
        sport="NBA",
        min_entry_fee=25,
        keyword="%",
        selected_from_candidate_count=3,
    )

    assert reason["mode"] == "primary_live"
    assert reason["criteria"]["min_entry_fee"] == 25
    assert reason["criteria"]["keyword"] == "%"
    assert reason["tie_breakers"] == [
        "entry_fee desc",
        "entries desc",
        "start_date desc",
        "dk_id desc",
    ]
    assert reason["selected_from_candidate_count"] == 3


def test_selection_reason_explicit_id_uses_contest_id_criteria():
    reason = snapshot_exporter.build_selection_reason(
        mode="explicit_id",
        sport="NBA",
        min_entry_fee=25,
        keyword="%",
        selected_from_candidate_count=1,
        contest_id=12345,
    )

    assert reason["criteria"] == {"contest_id": "12345"}


def test_candidate_summary_is_stably_ordered_and_bounded():
    rows = [
        ("1", "A", 10, "2026-02-13 10:00:00", 50, 1),
        ("2", "B", 20, "2026-02-13 11:00:00", 10, 0),
        ("3", "C", 20, "2026-02-13 12:00:00", 40, 0),
        ("4", "D", 20, "2026-02-13 12:00:00", 40, 0),
    ]
    summary = snapshot_exporter.summarize_candidates(rows, top_n=3)

    assert [item["contest_id"] for item in summary] == ["3", "4", "2"]


def test_rounding_applied_at_serialization_boundary():
    payload = {
        "snapshot_version": "v1",
        "snapshot_generated_at_utc": "2026-02-14T10:00:00Z",
        "sport": "NBA",
        "contest": {"contest_id": 123, "is_primary": True},
        "selection": {"selected_contest_id": 123, "reason": {}},
        "candidates": [],
        "cash_line": {"points": 112.555, "delta_to_cash": 0.0049},
        "vip_lineups": [],
        "players": [{"name": "P", "ownership_pct": 33.333333, "fantasy_points": 12.3456, "value": 4.5678}],
        "ownership": {"ownership_remaining_total_pct": 66.666666},
        "train_clusters": [],
        "standings": [{"entry_key": 987, "pmr": 1.239, "points": 110.336}],
        "truncation": {},
        "metadata": {"warnings": [], "missing_fields": [], "source_endpoints": []},
    }

    normalized = snapshot_exporter.normalize_snapshot_for_output(payload)

    assert normalized["ownership"]["ownership_remaining_total_pct"] == 66.6667
    assert normalized["cash_line"]["points"] == 112.56
    assert normalized["standings"][0]["pmr"] == 1.24
    assert normalized["players"][0]["ownership_pct"] == 33.3333
    assert normalized["players"][0]["fantasy_points"] == 12.35
    assert normalized["players"][0]["value"] == 4.57
    assert payload["ownership"]["ownership_remaining_total_pct"] == 66.666666


def test_ownership_remaining_total_pct_is_not_capped():
    payload = {
        "snapshot_version": "v1",
        "snapshot_generated_at_utc": "2026-02-14T10:00:00Z",
        "sport": "NBA",
        "contest": {"contest_id": "1", "is_primary": True},
        "selection": {"selected_contest_id": "1", "reason": {}},
        "candidates": [],
        "cash_line": {},
        "vip_lineups": [],
        "ownership": {"ownership_remaining_total_pct": 132.777777},
        "train_clusters": [],
        "standings": [{"entry_key": "a", "ownership_remaining_total_pct": 125.0199}],
        "truncation": {},
        "metadata": {"warnings": [], "missing_fields": [], "source_endpoints": []},
    }

    normalized = snapshot_exporter.normalize_snapshot_for_output(payload)

    assert normalized["ownership"]["ownership_remaining_total_pct"] == 132.7778
    assert normalized["standings"][0]["ownership_remaining_total_pct"] == 125.0199
    assert normalized["metadata"]["warnings"] == []


def test_cluster_id_is_stable_from_name_based_signature():
    cluster_id = snapshot_exporter.cluster_id_from_signature("A|B|C")
    assert cluster_id == hashlib.sha1("A|B|C".encode("utf-8")).hexdigest()[:12]


def test_timestamps_are_utc_iso_z():
    dt = datetime.datetime(2026, 2, 14, 12, 30, tzinfo=datetime.timezone.utc)
    assert snapshot_exporter.to_utc_iso(dt) == "2026-02-14T12:30:00Z"


def test_json_output_is_byte_stable():
    payload = {
        "snapshot_version": "v1",
        "snapshot_generated_at_utc": "2026-02-14T10:00:00Z",
        "sport": "NBA",
        "contest": {"contest_id": "1", "is_primary": True},
        "selection": {"selected_contest_id": "1", "reason": {}},
        "candidates": [],
        "cash_line": {},
        "vip_lineups": [],
        "ownership": {"ownership_remaining_total_pct": 1.0},
        "train_clusters": [],
        "standings": [],
        "truncation": {},
        "metadata": {"warnings": [], "missing_fields": [], "source_endpoints": []},
    }

    out1 = snapshot_exporter.snapshot_to_json(payload)
    out2 = snapshot_exporter.snapshot_to_json(payload)

    assert out1 == out2
    assert out1.endswith("\n")


def test_cli_export_fixture_calls_build_snapshot(monkeypatch, tmp_path):
    called = {}

    def fake_build_snapshot(**kwargs):
        called.update(kwargs)
        return {
            "snapshot_version": "v1",
            "snapshot_generated_at_utc": "2026-02-14T10:00:00Z",
            "sport": "NBA",
            "contest": _canonical_contest_seed(contest_id="1", name="NBA Contest"),
            "selection": {"selected_contest_id": "1", "reason": {}},
            "candidates": [],
            "cash_line": {},
            "vip_lineups": [],
            "ownership": {"ownership_remaining_total_pct": 1.0},
            "train_clusters": [],
            "standings": [],
            "truncation": {},
            "metadata": {"warnings": [], "missing_fields": [], "source_endpoints": []},
        }

    monkeypatch.setattr(export_command, "build_snapshot", fake_build_snapshot)
    args = Namespace(
        sport="nba",
        contest_id=None,
        out=str(tmp_path / "snapshot.json"),
        standings_limit=500,
    )
    rc = export_command.run_export_fixture(args)

    assert rc == 0
    assert called["sport"] == "NBA"
    assert called["standings_limit"] == 500


def test_cli_export_fixture_defaults_out_path_when_missing(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(export_command, "configure_runtime", lambda: None)
    monkeypatch.setattr(
        export_command,
        "build_snapshot",
        lambda **_kwargs: {
            "snapshot_version": "v1",
            "snapshot_generated_at_utc": "2026-02-14T10:00:00Z",
            "sport": "NBA",
            "contest": _canonical_contest_seed(contest_id="42", name="NBA Contest"),
            "selection": {"selected_contest_id": "42", "reason": {}},
            "candidates": [],
            "cash_line": {},
            "vip_lineups": [],
            "ownership": {"ownership_remaining_total_pct": 1.0},
            "train_clusters": [],
            "standings": [],
            "truncation": {},
            "metadata": {"warnings": [], "missing_fields": [], "source_endpoints": []},
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


def test_ids_are_serialized_as_strings():
    payload = {
        "snapshot_version": "v1",
        "snapshot_generated_at_utc": "2026-02-14T10:00:00Z",
        "sport": "NBA",
        "contest": {"contest_id": 123, "draft_group": 456, "is_primary": True},
        "selection": {"selected_contest_id": 123, "reason": {}},
        "candidates": [{"contest_id": 5}],
        "cash_line": {},
        "vip_lineups": [{"entry_key": 111}],
        "ownership": {"ownership_remaining_total_pct": 1.0},
        "train_clusters": [{"cluster_id": 99, "entry_keys": [9, 8]}],
        "standings": [{"entry_key": 10}],
        "truncation": {},
        "metadata": {"warnings": [], "missing_fields": [], "source_endpoints": []},
    }

    normalized = snapshot_exporter.normalize_snapshot_for_output(payload)
    assert normalized["contest"]["contest_id"] == "123"
    assert normalized["contest"]["draft_group"] == "456"
    assert normalized["selection"]["selected_contest_id"] == "123"
    assert normalized["candidates"][0]["contest_id"] == "5"
    assert normalized["vip_lineups"][0]["entry_key"] == "111"
    assert normalized["train_clusters"][0]["cluster_id"] == "99"
    assert normalized["train_clusters"][0]["entry_keys"] == ["9", "8"]
    assert normalized["standings"][0]["entry_key"] == "10"


def test_players_do_not_include_standings_position_field():
    payload = {
        "snapshot_version": "v1",
        "snapshot_generated_at_utc": "2026-02-14T10:00:00Z",
        "sport": "NBA",
        "contest": {"contest_id": "1", "is_primary": True},
        "selection": {"selected_contest_id": "1", "reason": {}},
        "candidates": [],
        "cash_line": {},
        "vip_lineups": [],
        "players": [{"name": "P", "position": "G", "salary": 5000}],
        "ownership": {"ownership_remaining_total_pct": 1.0},
        "train_clusters": [],
        "standings": [],
        "truncation": {},
        "metadata": {"warnings": [], "missing_fields": [], "source_endpoints": []},
    }

    normalized = snapshot_exporter.normalize_snapshot_for_output(payload)
    assert "standings_position" not in normalized["players"][0]


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

    def _fake_build_snapshot(*, sport: str, contest_id: int | None, standings_limit: int):
        return {
            "snapshot_version": "v1",
            "snapshot_generated_at_utc": "2026-02-14T10:00:00Z",
            "sport": sport,
            "contest": _canonical_contest_seed(contest_id=contest_id, name=f"{sport} Contest", sport=sport.lower()),
            "selection": {"selected_contest_id": contest_id, "reason": {}},
            "candidates": [],
            "cash_line": {},
            "vip_lineups": [],
            "players": [{"name": "A"}, {"name": "C"}],
            "ownership": {"ownership_remaining_total_pct": 1.0},
            "train_clusters": [],
            "standings": [],
            "truncation": {"limit": standings_limit},
            "metadata": {"warnings": [], "missing_fields": [], "source_endpoints": []},
        }

    monkeypatch.setattr(export_command, "build_snapshot", _fake_build_snapshot)
    out = tmp_path / "bundle.json"
    args = Namespace(
        item=["NBA:123", "GOLF:456"],
        out=str(out),
        standings_limit=42,
    )

    rc = export_command.run_export_bundle(args)
    payload = out.read_text(encoding="utf-8")

    assert rc == 0
    assert '"schema_version":2' in payload
    assert '"nba"' in payload
    assert '"golf"' in payload
    assert '"contest_id":"123"' in payload
    assert '"contest_id":"456"' in payload


def test_run_export_fixture_emits_envelope_and_contract_sections(monkeypatch, tmp_path):
    monkeypatch.setattr(export_command, "configure_runtime", lambda: None)
    monkeypatch.setattr(
        export_command,
        "build_snapshot",
        lambda **_kwargs: {
            "snapshot_version": "v1",
            "snapshot_generated_at_utc": "2026-02-14T10:00:00Z",
            "sport": "NBA",
            "contest": {
                **_canonical_contest_seed(contest_id=188080404, name="NBA Single Entry"),
                "start_time": "2026-02-14T01:00:00Z",
                "entry_fee_cents": None,
                "entry_fee": 10,
                "prize_pool_cents": 500000,
                "positions_paid": 200,
            },
            "selection": {
                "selected_contest_id": 188080404,
                "reason": {"mode": "explicit_id"},
            },
            "cash_line": {"cutoff_type": "positions_paid", "rank": 200, "points": 250.5},
            "vip_lineups": [
                {"username": "vip1", "entry_key": "1", "rank": 2, "pts": 249.0, "pmr": 12.0, "lineup": ["A", "B"]}
            ],
            "players": [{"name": "A"}, {"name": "B"}],
            "ownership": {
                "ownership_remaining_total_pct": 123.4,
                "top_remaining_players": [{"player_name": "A", "ownership_remaining_pct": 40.0}],
            },
            "train_clusters": [
                {
                    "cluster_id": "abc123",
                    "user_count": 2,
                    "rank": 3,
                    "points": 249.0,
                    "pmr": 10.0,
                    "lineup_signature": "A|B",
                    "entry_keys": ["1"],
                }
            ],
            "standings": [
                {
                    "entry_key": "1",
                    "username": "u1",
                    "rank": 2,
                    "points": 249.0,
                    "pmr": "12.0",
                    "ownership_remaining_total_pct": "33.0",
                }
            ],
            "truncation": {
                "applied": True,
                "total_rows_before_truncation": 500,
            },
            "metadata": {"warnings": [], "missing_fields": [], "source_endpoints": []},
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
    assert payload["schema_version"] == 2
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
    assert sport["primary_contest"]["selection_reason"] == "explicit_id contest_id=188080404"
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
    assert isinstance(contest.get("entries_count"), int)
    assert "start_time_utc" not in contest
    assert sport["primary_contest"]["contest_key"] is not None
    assert sport["primary_contest"]["contest_key"] == contest["contest_key"]
    assert contest["is_primary"] is True
    assert contest["entries_count"] == 1000
    assert contest["live_metrics"]["cash_line"]["cutoff_type"] == "rank"
    assert contest["live_metrics"]["cash_line"]["rank_cutoff"] == 200
    assert contest["live_metrics"]["cash_line"]["points_cutoff"] == 250.5
    assert contest["ownership_watchlist"]["entries"][0]["display_name"] == "A"
    assert contest["ownership_watchlist"]["top_n_default"] == 10
    assert "ownership_remaining_total_pct" in contest["ownership_watchlist"]
    assert contest["standings"]["is_truncated"] is True
    assert contest["standings"]["total_rows"] == 500
    assert contest["standings"]["rows"][0]["display_name"] == "u1"
    assert "ownership_remaining_pct" in contest["standings"]["rows"][0]
    assert "ownership_remaining_total_pct" not in contest["standings"]["rows"][0]
    assert isinstance(contest["standings"]["rows"][0]["pmr"], float)
    assert contest["train_clusters"]["clusters"][0]["composition"][0]["player_name"] == "A"
    assert contest["train_clusters"]["cluster_rule"] == {"type": "shared_slots", "min_shared": 2}
    assert contest["train_clusters"]["clusters"][0]["cluster_key"] == "abc123"
    assert contest["train_clusters"]["clusters"][0]["entry_count"] == 2
    assert contest["train_clusters"]["clusters"][0]["sample_entries"][0]["entry_key"] == "1"
    assert contest["train_clusters"]["clusters"][0]["sample_entries"][0]["display_name"] == "u1"
    assert contest["vip_lineups"][0]["slots"][0]["player_name"] == "A"
    assert contest["vip_lineups"][0]["display_name"] == "vip1"
    assert contest["vip_lineups"][0]["live"]["current_rank"] == 2
    assert contest["vip_lineups"][0]["live"]["pmr"] == 12.0
    assert isinstance(contest["vip_lineups"][0]["live"]["pmr"], float)
    assert "username" not in json.dumps(payload)
    assert "selection" not in sport
    assert "contest" not in sport
    assert "metadata" not in sport
    assert "candidates" not in sport
    assert "cash_line" not in sport
    assert "ownership" not in sport
    assert "standings" not in sport


def test_run_export_bundle_emits_contests_primary_contest_and_players(monkeypatch, tmp_path):
    monkeypatch.setattr(export_command, "configure_runtime", lambda: None)

    def _fake_build_snapshot(*, sport: str, contest_id: int | None, standings_limit: int):
        return {
            "snapshot_version": "v1",
            "snapshot_generated_at_utc": "2026-02-14T10:00:00Z",
            "sport": sport,
            "contest": _canonical_contest_seed(contest_id=contest_id, name=f"{sport} contest", sport=sport.lower()),
            "selection": {"selected_contest_id": contest_id, "reason": {"mode": "explicit_id"}},
            "cash_line": {"cutoff_type": "positions_paid", "rank": 10, "points": 99.9},
            "vip_lineups": [],
            "players": [{"name": "Player One"}],
            "ownership": {"ownership_remaining_total_pct": 10.0, "top_remaining_players": []},
            "train_clusters": [],
            "standings": [],
            "truncation": {"applied": False, "total_rows_before_truncation": 0},
            "metadata": {"warnings": [], "missing_fields": [], "source_endpoints": []},
        }

    monkeypatch.setattr(export_command, "build_snapshot", _fake_build_snapshot)

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
    assert payload["schema_version"] == 2
    assert sorted(payload["sports"].keys()) == ["golf", "nba"]
    assert payload["sports"]["nba"]["primary_contest"]["contest_id"] == "123"
    assert isinstance(payload["sports"]["nba"]["primary_contest"]["selection_reason"], str)
    assert payload["sports"]["golf"]["contests"][0]["contest_id"] == "456"
    assert payload["sports"]["nba"]["players"][0]["name"] == "Player One"
    assert "selection" not in payload["sports"]["nba"]
    assert "contest" not in payload["sports"]["nba"]
    assert payload["sports"]["golf"]["contests"][0]["ownership_watchlist"]["top_n_default"] == 10


def test_run_publish_snapshot_writes_latest_and_manifest(monkeypatch, tmp_path):
    root = tmp_path / "public"
    snapshot_file = root / "snapshots" / "live-1.json"
    snapshot_file.parent.mkdir(parents=True, exist_ok=True)
    snapshot_file.write_text(
        snapshot_exporter.to_stable_json(
            {
                "schema_version": 2,
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

    # Re-running with same snapshot_at updates in place (no duplicate entries).
    rc_second = export_command.run_publish_snapshot(args)
    manifest_second = json.loads((root / "manifest" / "2026-02-15.json").read_text(encoding="utf-8"))
    assert rc_second == 0
    assert len(manifest_second["snapshots"]) == 1


def test_distance_to_cash_metrics_points_and_rank_delta(monkeypatch):
    monkeypatch.setattr(
        snapshot_exporter,
        "collect_snapshot_data",
        lambda **_kwargs: {
            "snapshot_version": "v1",
            "sport": "NBA",
            "contest": {"contest_id": 123, "is_primary": True, "name": "x"},
            "selection": {"selected_contest_id": 123, "reason": {}},
            "candidates": [],
            "cash_line": {"cutoff_type": "rank", "rank": 10, "points": 100.0},
            "vip_lineups": [{"entry_key": "vip-1", "pts": 102.5, "rank": 8, "username": "vip"}],
            "players": [{"name": "A"}, {"name": "C"}],
            "ownership": {"ownership_remaining_total_pct": 1.0, "top_remaining_players": []},
            "train_clusters": [],
            "standings": [],
            "truncation": {},
            "metadata": {"warnings": [], "missing_fields": [], "source_endpoints": []},
        },
    )

    snapshot = snapshot_exporter.build_snapshot(sport="NBA")
    envelope = snapshot_exporter.build_dashboard_envelope({"NBA": snapshot})
    metrics = envelope["sports"]["nba"]["contests"][0]["metrics"]["distance_to_cash"]

    assert metrics["cutoff_points"] == 100.0
    assert metrics["per_vip"][0]["points_delta"] == 2.5
    assert metrics["per_vip"][0]["rank_delta"] == 2


def test_ownership_summary_metrics_per_vip_formulas(monkeypatch):
    monkeypatch.setattr(
        snapshot_exporter,
        "collect_snapshot_data",
        lambda **_kwargs: {
            "snapshot_version": "v1",
            "sport": "NBA",
            "contest": {"contest_id": 123, "is_primary": True, "name": "x"},
            "selection": {"selected_contest_id": 123, "reason": {}},
            "candidates": [],
            "cash_line": {"cutoff_type": "rank", "rank": 10, "points": 100.0},
            "vip_lineups": [
                {
                    "entry_key": "vip-1",
                    "username": "vip",
                    "players": [
                        {"pos": "PG", "name": "Javon Small", "ownership": 0.8467},
                        {"pos": "SG", "name": "Anthony Edwards", "ownership": 0.7372},
                        {"pos": "SF", "name": "Jahmai Mashack", "ownership": "31.39%"},
                    ],
                }
            ],
            "players": [
                {"name": "Javon Small", "game_status": "In Progress"},
                {"name": "Anthony Edwards", "game_status": "Final"},
                {"name": "Jahmai Mashack", "game_status": "Halftime"},
            ],
            "ownership": {"ownership_remaining_total_pct": 1.0, "top_remaining_players": []},
            "train_clusters": [],
            "standings": [{"entry_key": "vip-1", "username": "vip"}],
            "truncation": {},
            "metadata": {"warnings": [], "missing_fields": [], "source_endpoints": []},
        },
    )

    snapshot = snapshot_exporter.build_snapshot(sport="NBA")
    envelope = snapshot_exporter.build_dashboard_envelope({"NBA": snapshot})
    summary = envelope["sports"]["nba"]["contests"][0]["metrics"]["ownership_summary"]

    assert summary["source"] == "vip_lineup_players"
    assert summary["scope"] == "vip_lineup"
    assert len(summary["per_vip"]) == 1
    row = summary["per_vip"][0]
    assert row["entry_key"] == "vip-1"
    assert row["total_ownership_pct"] == 189.78
    assert row["ownership_in_play_pct"] == 116.06
    assert row["is_partial"] is False


def test_ownership_summary_omits_rows_with_missing_keys(monkeypatch):
    monkeypatch.setattr(
        snapshot_exporter,
        "collect_snapshot_data",
        lambda **_kwargs: {
            "snapshot_version": "v1",
            "sport": "NBA",
            "contest": {"contest_id": 123, "is_primary": True, "name": "x"},
            "selection": {"selected_contest_id": 123, "reason": {}},
            "candidates": [],
            "cash_line": {},
            "vip_lineups": [
                {
                    "entry_key": "vip-1",
                    "username": "vip",
                    "players": [{"pos": "PG", "name": "Javon Small", "ownership": 0.5, "game_status": "live"}],
                },
                {
                    "username": "no_key_vip",
                    "players": [{"pos": "SG", "name": "Anthony Edwards", "ownership": 0.4, "game_status": "live"}],
                },
            ],
            "players": [{"name": "Javon Small", "game_status": "In Progress"}],
            "ownership": {"ownership_remaining_total_pct": 1.0, "top_remaining_players": []},
            "train_clusters": [],
            "standings": [{"entry_key": "vip-1", "username": "vip"}],
            "truncation": {},
            "metadata": {"warnings": [], "missing_fields": [], "source_endpoints": []},
        },
    )

    snapshot = snapshot_exporter.build_snapshot(sport="NBA")
    envelope = snapshot_exporter.build_dashboard_envelope({"NBA": snapshot})
    summary = envelope["sports"]["nba"]["contests"][0]["metrics"]["ownership_summary"]

    assert len(summary["per_vip"]) == 1
    assert summary["per_vip"][0]["entry_key"] == "vip-1"


def test_non_cashing_metrics_emits_users_avg_and_top_list(monkeypatch):
    monkeypatch.setattr(
        snapshot_exporter,
        "collect_snapshot_data",
        lambda **_kwargs: {
            "snapshot_version": "v1",
            "sport": "NBA",
            "contest": {"contest_id": 123, "is_primary": True, "name": "x"},
            "selection": {"selected_contest_id": 123, "reason": {}},
            "candidates": [],
            "cash_line": {},
            "vip_lineups": [],
            "players": [],
            "ownership": {
                "ownership_remaining_total_pct": 120.0,
                "non_cashing_user_count": 109,
                "non_cashing_avg_pmr": 342.83,
                "top_remaining_players": [
                    {"player_name": "Jalen Johnson", "ownership_remaining_pct": 92.66},
                    {"player_name": "Javon Small", "ownership_remaining_pct": 88.99},
                ],
            },
            "train_clusters": [],
            "standings": [],
            "truncation": {},
            "metadata": {"warnings": [], "missing_fields": [], "source_endpoints": []},
        },
    )

    snapshot = snapshot_exporter.build_snapshot(sport="NBA")
    envelope = snapshot_exporter.build_dashboard_envelope({"NBA": snapshot})
    non_cashing = envelope["sports"]["nba"]["contests"][0]["metrics"]["non_cashing"]

    assert non_cashing["users_not_cashing"] == 109
    assert non_cashing["avg_pmr_remaining"] == 342.83
    assert non_cashing["top_remaining_players"][0]["player_name"] == "Jalen Johnson"
    assert non_cashing["top_remaining_players"][0]["ownership_remaining_pct"] == 92.66


def test_non_cashing_metrics_omits_when_no_source_fields(monkeypatch):
    monkeypatch.setattr(
        snapshot_exporter,
        "collect_snapshot_data",
        lambda **_kwargs: {
            "snapshot_version": "v1",
            "sport": "NBA",
            "contest": {"contest_id": 123, "is_primary": True, "name": "x"},
            "selection": {"selected_contest_id": 123, "reason": {}},
            "candidates": [],
            "cash_line": {},
            "vip_lineups": [],
            "players": [],
            "ownership": {"ownership_remaining_total_pct": 120.0, "top_remaining_players": []},
            "train_clusters": [],
            "standings": [],
            "truncation": {},
            "metadata": {"warnings": [], "missing_fields": [], "source_endpoints": []},
        },
    )

    snapshot = snapshot_exporter.build_snapshot(sport="NBA")
    envelope = snapshot_exporter.build_dashboard_envelope({"NBA": snapshot})
    metrics = envelope["sports"]["nba"]["contests"][0].get("metrics", {})

    assert "non_cashing" not in metrics


def test_threat_metrics_leverage_and_vip_counts(monkeypatch):
    monkeypatch.setattr(
        snapshot_exporter,
        "collect_snapshot_data",
        lambda **_kwargs: {
            "snapshot_version": "v1",
            "sport": "NBA",
            "contest": {"contest_id": 123, "is_primary": True, "name": "x"},
            "selection": {"selected_contest_id": 123, "reason": {}},
            "candidates": [],
            "cash_line": {"cutoff_type": "points", "points": 100.0},
            "vip_lineups": [
                {
                    "entry_key": "vip-1",
                    "pts": 99.0,
                    "rank": 50,
                    "username": "vip",
                    "players": [{"name": "A"}, {"name": "C"}],
                }
            ],
            "players": [{"name": "A"}, {"name": "C"}],
            "ownership": {
                "ownership_remaining_total_pct": 120.0,
                "top_remaining_players": [
                    {"player_name": "A", "ownership_remaining_pct": 40.0},
                    {"player_name": "B", "ownership_remaining_pct": 20.0},
                ],
            },
            "train_clusters": [],
            "standings": [
                {
                    "entry_key": "vip-1",
                    "username": "vip",
                    "ownership_remaining_total_pct": 30.0,
                }
            ],
            "truncation": {},
            "metadata": {"warnings": [], "missing_fields": [], "source_endpoints": []},
        },
    )

    snapshot = snapshot_exporter.build_snapshot(sport="NBA")
    envelope = snapshot_exporter.build_dashboard_envelope({"NBA": snapshot})
    threat = envelope["sports"]["nba"]["contests"][0]["metrics"]["threat"]

    assert threat["leverage_semantics"] == "positive=unique"
    assert threat["field_remaining_scope"] == "watchlist"
    assert threat["field_remaining_pct"] == 120.0
    assert threat["top_swing_players"][0]["player_name"] == "A"
    assert threat["top_swing_players"][0]["vip_count"] == 1
    assert threat["vip_vs_field_leverage"][0]["uniqueness_delta_pct"] == 90.0


def test_distance_to_cash_metrics_rank_only_emits_rank_delta(monkeypatch):
    monkeypatch.setattr(
        snapshot_exporter,
        "collect_snapshot_data",
        lambda **_kwargs: {
            "snapshot_version": "v1",
            "sport": "NBA",
            "contest": {"contest_id": 123, "is_primary": True, "name": "x"},
            "selection": {"selected_contest_id": 123, "reason": {}},
            "candidates": [],
            "cash_line": {"cutoff_type": "rank", "rank": 10, "points": None},
            "vip_lineups": [{"entry_key": "vip-1", "pts": None, "rank": 8, "username": "vip"}],
            "players": [],
            "ownership": {"ownership_remaining_total_pct": 1.0, "top_remaining_players": []},
            "train_clusters": [],
            "standings": [],
            "truncation": {},
            "metadata": {"warnings": [], "missing_fields": [], "source_endpoints": []},
        },
    )

    snapshot = snapshot_exporter.build_snapshot(sport="NBA")
    envelope = snapshot_exporter.build_dashboard_envelope({"NBA": snapshot})
    metrics = envelope["sports"]["nba"]["contests"][0]["metrics"]["distance_to_cash"]

    assert "cutoff_points" not in metrics
    assert len(metrics["per_vip"]) == 1
    assert metrics["per_vip"][0]["rank_delta"] == 2
    assert "points_delta" not in metrics["per_vip"][0]


def test_train_metrics_ranked_and_top_clusters(monkeypatch):
    monkeypatch.setattr(
        snapshot_exporter,
        "collect_snapshot_data",
        lambda **_kwargs: {
            "snapshot_version": "v1",
            "sport": "NBA",
            "contest": {"contest_id": 123, "is_primary": True, "name": "x"},
            "selection": {"selected_contest_id": 123, "reason": {}},
            "candidates": [],
            "cash_line": {},
            "vip_lineups": [],
            "players": [],
            "ownership": {"ownership_remaining_total_pct": 1.0, "top_remaining_players": []},
            "train_clusters": [
                {"cluster_id": "c1", "user_count": 10, "rank": 3, "pmr": 1.5},
                {"cluster_id": "c2", "user_count": 5, "rank": 1, "pmr": 2.0},
                {"cluster_id": "c3", "user_count": 20, "pmr": 0.5},
            ],
            "standings": [],
            "truncation": {},
            "metadata": {"warnings": [], "missing_fields": [], "source_endpoints": []},
        },
    )

    snapshot = snapshot_exporter.build_snapshot(sport="NBA")
    envelope = snapshot_exporter.build_dashboard_envelope({"NBA": snapshot})
    trains = envelope["sports"]["nba"]["contests"][0]["metrics"]["trains"]

    assert trains["recommended_top_n"] == 5
    assert trains["ranked_clusters"][0]["cluster_key"] == "c2"
    assert trains["ranked_clusters"][0]["rank"] == 1
    assert trains["top_clusters"][0]["cluster_key"] == "c2"


def test_vip_lineups_support_user_and_players_shape(monkeypatch, tmp_path):
    monkeypatch.setattr(export_command, "configure_runtime", lambda: None)
    monkeypatch.setattr(
        export_command,
        "build_snapshot",
        lambda **_kwargs: {
            "snapshot_version": "v1",
            "snapshot_generated_at_utc": "2026-02-14T10:00:00Z",
            "sport": "NBA",
            "contest": _canonical_contest_seed(contest_id=1, name="x"),
            "selection": {"selected_contest_id": 1, "reason": {"mode": "explicit_id"}},
            "cash_line": {"cutoff_type": "rank", "rank": 10, "points": 100.0},
            "players": [{"name": "Alpha"}, {"name": "Beta"}],
            "ownership": {"ownership_remaining_total_pct": 1.0, "top_remaining_players": []},
            "standings": [
                {
                    "entry_key": "777",
                    "username": "vip_user",
                    "rank": "5",
                    "points": "110.0",
                    "pmr": "0",
                    "ownership_remaining_total_pct": "20.0",
                    "payout_cents": 1500,
                }
            ],
            "train_clusters": [],
            "vip_lineups": [
                {
                    "user": "vip_user",
                    "pts": 110.0,
                    "rank": 5,
                    "pmr": 0.0,
                    "players": [{"pos": "PG", "name": "Alpha"}, {"pos": "SG", "name": "Beta"}],
                }
            ],
            "truncation": {"applied": False, "total_rows_before_truncation": 1},
            "metadata": {"warnings": [], "missing_fields": [], "source_endpoints": []},
        },
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
        "build_snapshot",
        lambda **_kwargs: {
            "snapshot_version": "v1",
            "snapshot_generated_at_utc": "2026-02-14T10:00:00Z",
            "sport": "NBA",
            "contest": _canonical_contest_seed(contest_id=1, name="x"),
            "selection": {"selected_contest_id": 1, "reason": {"mode": "explicit_id"}},
            "cash_line": {"cutoff_type": "rank", "rank": 10, "points": 100.0},
            "players": [
                {"name": "Javon Small", "game_status": "In Progress"},
                {"name": "Anthony Edwards", "game_status": "Final"},
            ],
            "ownership": {"ownership_remaining_total_pct": 1.0, "top_remaining_players": []},
            "standings": [
                {
                    "entry_key": "777",
                    "username": "vip_user",
                    "rank": "5",
                    "points": "110.0",
                    "pmr": "0",
                    "ownership_remaining_total_pct": "20.0",
                    "payout_cents": 1500,
                }
            ],
            "train_clusters": [],
            "vip_lineups": [
                {
                    "user": "vip_user",
                    "pts": 110.0,
                    "rank": 5,
                    "pmr": 0.0,
                    "players": [
                        {
                            "pos": "PG",
                            "name": "Javon Small",
                            "ownership": 0.8467,
                            "salary": "$3,500",
                            "pts": "7.25",
                            "value": "2.07",
                            "rtProj": "21.11",
                            "timeStatus": "38.02",
                            "stats": "1 REB, 1 STL, 4 PTS",
                        },
                        {
                            "pos": "C",
                            "name": "LOCKED 🔒",
                            "ownership": "",
                            "salary": "",
                            "pts": "",
                            "value": "",
                            "rtProj": "",
                            "timeStatus": "",
                            "stats": "",
                        },
                    ],
                }
            ],
            "truncation": {"applied": False, "total_rows_before_truncation": 1},
            "metadata": {"warnings": [], "missing_fields": [], "source_endpoints": []},
        },
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


def test_vip_entry_key_backfill_requires_unique_display_name(monkeypatch, tmp_path):
    monkeypatch.setattr(export_command, "configure_runtime", lambda: None)
    monkeypatch.setattr(
        export_command,
        "build_snapshot",
        lambda **_kwargs: {
            "snapshot_version": "v1",
            "snapshot_generated_at_utc": "2026-02-14T10:00:00Z",
            "sport": "NBA",
            "contest": _canonical_contest_seed(contest_id=1, name="x"),
            "selection": {"selected_contest_id": 1, "reason": {"mode": "explicit_id"}},
            "cash_line": {"cutoff_type": "rank", "rank": 10, "points": 100.0},
            "players": [{"name": "Alpha"}],
            "ownership": {"ownership_remaining_total_pct": 1.0, "top_remaining_players": []},
            "standings": [
                {"entry_key": "111", "username": "dup_user", "rank": 5, "points": 110.0, "pmr": 0.0},
                {"entry_key": "222", "username": "dup_user", "rank": 8, "points": 101.0, "pmr": 1.0},
            ],
            "train_clusters": [],
            "vip_lineups": [{"user": "dup_user", "players": [{"pos": "PG", "name": "Alpha"}]}],
            "truncation": {"applied": False, "total_rows_before_truncation": 2},
            "metadata": {"warnings": [], "missing_fields": [], "source_endpoints": []},
        },
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
        "build_snapshot",
        lambda **_kwargs: {
            "snapshot_version": "v1",
            "snapshot_generated_at_utc": "2026-02-14T10:00:00Z",
            "sport": "NBA",
            "contest": _canonical_contest_seed(contest_id=1, name="x"),
            "selection": {"selected_contest_id": 1, "reason": {"mode": "explicit_id"}},
            "cash_line": {"cutoff_type": "rank", "rank": 10, "points": 100.0},
            "players": [],
            "ownership": {"ownership_remaining_total_pct": 1.0, "top_remaining_players": []},
            "standings": [
                {"entry_key": "a", "username": "u1", "rank": 1, "points": 120.0, "pmr": 0.0, "payout_cents": "2500"},
                {"entry_key": "b", "username": "u2", "rank": 40, "points": 90.0, "pmr": 2.0, "payout_cents": None},
            ],
            "train_clusters": [],
            "vip_lineups": [],
            "truncation": {"applied": False, "total_rows_before_truncation": 2},
            "metadata": {"warnings": [], "missing_fields": [], "source_endpoints": []},
        },
    )
    out = tmp_path / "cashing-rule.json"
    rc = export_command.run_export_fixture(Namespace(sport="NBA", contest_id=1, out=str(out), standings_limit=100))
    payload = json.loads(out.read_text(encoding="utf-8"))
    rows = payload["sports"]["nba"]["contests"][0]["standings"]["rows"]

    assert rc == 0
    assert rows[0]["payout_cents"] == 2500
    assert rows[0]["is_cashing"] is True
    assert rows[1]["payout_cents"] is None
    assert rows[1]["is_cashing"] is False


def test_validate_canonical_snapshot_detects_disallowed_keys_and_numeric_strings():
    payload = {
        "schema_version": 2,
        "snapshot_at": "2026-02-14T00:00:00Z",
        "generated_at": "2026-02-14T00:00:00Z",
        "sports": {
            "nba": {
                "status": "ok",
                "updated_at": "2026-02-14T00:00:00Z",
                "players": [],
                "contests": [
                    {
                        "contest_id": "123",
                        "standings": {
                            "updated_at": "2026-02-14T00:00:00Z",
                            "rows": [{"username": "bad", "points": "99.5"}],
                        },
                    }
                ],
            }
        },
    }

    violations = snapshot_exporter.validate_canonical_snapshot(payload)

    assert "disallowed_key:sports.nba.contests.0.standings.rows.0.username" in violations
    assert "numeric_string:sports.nba.contests.0.standings.rows.0.points" in violations


def test_validate_canonical_snapshot_has_required_field_and_type_coverage():
    required_field_cases = {
        "contest_id": "missing_required:sports.nba.contests.0.contest_id",
        "contest_key": "missing_required:sports.nba.contests.0.contest_key",
        "name": "missing_required:sports.nba.contests.0.name",
        "sport": "missing_required:sports.nba.contests.0.sport",
        "contest_type": "missing_required:sports.nba.contests.0.contest_type",
        "start_time": "missing_required:sports.nba.contests.0.start_time",
        "state": "missing_required:sports.nba.contests.0.state",
        "entry_fee_cents": "missing_required:sports.nba.contests.0.entry_fee_cents",
        "prize_pool_cents": "missing_required:sports.nba.contests.0.prize_pool_cents",
        "currency": "missing_required:sports.nba.contests.0.currency",
        "max_entries": "missing_required:sports.nba.contests.0.max_entries",
        "max_entries_per_user": "missing_required:sports.nba.contests.0.max_entries_per_user",
    }
    for field_name, expected_violation in required_field_cases.items():
        payload = _valid_envelope_for_validation()
        payload["sports"]["nba"]["contests"][0][field_name] = None
        violations = snapshot_exporter.validate_canonical_snapshot(payload)
        assert expected_violation in violations

    wrong_type_cases = {
        "contest_id": 123,
        "contest_key": 123,
        "name": 123,
        "sport": 123,
        "contest_type": 123,
        "start_time": 123,
        "state": 123,
        "entry_fee_cents": "1000",
        "prize_pool_cents": "250000",
        "currency": 123,
        "entries_count": "1000",
        "max_entries": "1000",
        "max_entries_per_user": "1",
    }
    for field_name, wrong_value in wrong_type_cases.items():
        payload = _valid_envelope_for_validation()
        payload["sports"]["nba"]["contests"][0][field_name] = wrong_value
        violations = snapshot_exporter.validate_canonical_snapshot(payload)
        assert f"type_mismatch:sports.nba.contests.0.{field_name}" in violations


def test_validate_canonical_snapshot_allows_omitting_entries_count():
    payload = _valid_envelope_for_validation()
    payload["sports"]["nba"]["contests"][0].pop("entries_count")
    violations = snapshot_exporter.validate_canonical_snapshot(payload)

    assert "missing_required:sports.nba.contests.0.entries_count" not in violations
    assert "type_mismatch:sports.nba.contests.0.entries_count" not in violations


def test_validate_canonical_snapshot_detects_primary_contest_key_mismatch():
    payload = _valid_envelope_for_validation()
    payload["sports"]["nba"]["primary_contest"]["contest_key"] = "nba:999"
    violations = snapshot_exporter.validate_canonical_snapshot(payload)

    assert "mismatch:sports.nba.primary_contest.contest_key" in violations


def test_validate_canonical_snapshot_requires_primary_contest_when_contests_present():
    payload = _valid_envelope_for_validation()
    payload["sports"]["nba"].pop("primary_contest")
    violations = snapshot_exporter.validate_canonical_snapshot(payload)

    assert "missing_required:sports.nba.primary_contest" in violations


def test_normalize_contest_state_prefers_authoritative_flags():
    assert snapshot_exporter._normalize_contest_state(None, 1) == "completed"
    assert snapshot_exporter._normalize_contest_state("In Progress", 0) == "live"
    assert snapshot_exporter._normalize_contest_state("scheduled", 0) == "upcoming"
    assert snapshot_exporter._normalize_contest_state("", 0) is None


def test_canonical_contest_contract_does_not_fabricate_missing_required_fields():
    contest = snapshot_exporter._canonical_contest_contract(
        {"contest_id": 123, "sport": "nba"},
        sport="nba",
    )

    assert contest["contest_id"] == "123"
    assert contest["contest_key"] == "nba:123"
    assert contest["state"] is None
    assert contest["entry_fee_cents"] is None
    assert contest["prize_pool_cents"] is None
    assert contest["start_time"] is None
    assert contest["max_entries_per_user"] is None


def test_collect_snapshot_data_sources_prize_pool_from_db_metadata(monkeypatch, tmp_path):
    class _FakeSport:
        name = "NBA"
        sheet_min_entry_fee = 25
        keyword = "%"

    class _FakeContestDb:
        def get_live_contest_candidates(self, *_args, **_kwargs):
            return []

        def get_live_contest(self, *_args, **_kwargs):
            return (123, "NBA Contest", 777, 10, "2026-02-14 01:00:00")

        def get_contest_by_id(self, *_args, **_kwargs):
            return (123, "NBA Contest", 777, 10, "2026-02-14 01:00:00", 10, 1000)

        def get_contest_state(self, *_args, **_kwargs):
            return ("In Progress", 0)

        def get_contest_contract_metadata(self, *_args, **_kwargs):
            return (250000, 1500, 1, 114)

        def close(self):
            return None

    class _FakeDraftKings:
        def download_salary_csv(self, _sport, _draft_group, filename):
            path = tmp_path / "salary.csv"
            path.write_text("Position,Name,Salary\nPG,A,5000\n", encoding="utf-8")

        def download_contest_rows(self, *_args, **_kwargs):
            return [["Rank", "EntryId"], ["1", "123"]]

        def get_vip_lineups(self, *_args, **_kwargs):
            return []

    class _FakeResults:
        def __init__(self, *_args, **_kwargs):
            self.vip_list = []
            self.players = {}
            self.users = []
            self.non_cashing_users = 0
            self.non_cashing_players = {}
            self.non_cashing_avg_pmr = 0.0
            self.min_rank = 0
            self.min_cash_pts = None

    class _FakeTrainFinder:
        def __init__(self, _users):
            pass

        def get_users_above_salary_spent(self, _limit):
            return {}

    monkeypatch.setattr(snapshot_exporter, "_sport_choices", lambda: {"NBA": _FakeSport})
    monkeypatch.setattr(snapshot_exporter, "ContestDatabase", lambda _path: _FakeContestDb())
    monkeypatch.setattr(snapshot_exporter, "Draftkings", _FakeDraftKings)
    monkeypatch.setattr(snapshot_exporter, "Results", _FakeResults)
    monkeypatch.setattr(snapshot_exporter, "TrainFinder", _FakeTrainFinder)
    monkeypatch.setattr(snapshot_exporter, "load_vips", lambda: [])
    monkeypatch.setattr(snapshot_exporter.state, "contests_db_path", lambda: tmp_path / "contests.db")
    monkeypatch.setattr(snapshot_exporter, "SALARY_DIR", str(tmp_path))

    snapshot = snapshot_exporter.collect_snapshot_data(sport="NBA", standings_limit=10)
    contest = snapshot["contest"]

    assert contest["prize_pool"] == 250000
    assert contest["max_entries"] == 1500
    assert contest["max_entries_per_user"] == 1
    assert contest["entries"] == 1500


def test_collect_snapshot_data_uses_leaderboard_payout_for_cashing(monkeypatch, tmp_path):
    class _FakeSport:
        name = "NBA"
        sheet_min_entry_fee = 25
        keyword = "%"

    class _FakePlayer:
        name = "A"
        pos = "PG"
        roster_pos = ["PG"]
        salary = 5000
        team_abbv = "LAL"
        game_info = "Final"
        matchup_info = "LAL@BOS"
        ownership = 0.2
        fpts = 12.0
        value = 2.4

    class _FakeUser:
        rank = 6
        player_id = "ek1"
        name = "vip1"
        pmr = "0"
        pts = 336.25

    class _FakeContestDb:
        def get_live_contest_candidates(self, *_args, **_kwargs):
            return []

        def get_contest_by_id(self, *_args, **_kwargs):
            return (123, "NBA Contest", 777, 50, "2026-02-14 01:00:00", 10, 1500)

        def get_contest_state(self, *_args, **_kwargs):
            return ("In Progress", 0)

        def get_contest_contract_metadata(self, *_args, **_kwargs):
            return (250000, 1500, 1, 114)

        def close(self):
            return None

    class _FakeDraftKings:
        def download_salary_csv(self, _sport, _draft_group, filename):
            path = tmp_path / "salary.csv"
            path.write_text("Position,Name,Salary\nPG,A,5000\n", encoding="utf-8")

        def get_leaderboard(self, *_args, **_kwargs):
            return {"leaderBoard": [{"entryKey": "ek1", "winningValue": 20}]}

        def download_contest_rows(self, *_args, **_kwargs):
            return [
                ["Rank", "EntryId", "EntryName", "TimeRemaining", "Points", "Lineup"],
                ["6", "ek1", "vip1", "0", "336.25", "PG A"],
            ]

        def get_vip_lineups(self, *_args, **_kwargs):
            return [{"user": "vip1", "entry_key": "ek1", "players": [{"slot": "PG", "name": "A"}]}]

    class _FakeResults:
        def __init__(self, *_args, **_kwargs):
            self.vip_list = [_FakeUser()]
            self.players = {"A": _FakePlayer()}
            self.users = [_FakeUser()]
            self.non_cashing_users = 0
            self.non_cashing_players = {}
            self.non_cashing_avg_pmr = 0.0
            self.min_rank = 50
            self.min_cash_pts = 325.25

    class _FakeTrainFinder:
        def __init__(self, _users):
            pass

        def get_users_above_salary_spent(self, _limit):
            return {}

    monkeypatch.setattr(snapshot_exporter, "_sport_choices", lambda: {"NBA": _FakeSport})
    monkeypatch.setattr(snapshot_exporter, "ContestDatabase", lambda _path: _FakeContestDb())
    monkeypatch.setattr(snapshot_exporter, "Draftkings", _FakeDraftKings)
    monkeypatch.setattr(snapshot_exporter, "Results", _FakeResults)
    monkeypatch.setattr(snapshot_exporter, "TrainFinder", _FakeTrainFinder)
    monkeypatch.setattr(snapshot_exporter, "load_vips", lambda: ["vip1"])
    monkeypatch.setattr(snapshot_exporter.state, "contests_db_path", lambda: tmp_path / "contests.db")
    monkeypatch.setattr(snapshot_exporter, "SALARY_DIR", str(tmp_path))

    snapshot = snapshot_exporter.collect_snapshot_data(sport="NBA", contest_id=123, standings_limit=10)
    assert snapshot["standings"][0]["payout_cents"] == 2000

    sport_payload = snapshot_exporter.build_dashboard_sport_snapshot(snapshot, "2026-02-14T02:00:00Z")
    contest = sport_payload["contests"][0]
    assert contest["standings"]["rows"][0]["payout_cents"] == 2000
    assert contest["standings"]["rows"][0]["is_cashing"] is True
    assert contest["vip_lineups"][0]["live"]["payout_cents"] == 2000
    assert contest["vip_lineups"][0]["live"]["is_cashing"] is True


def test_collect_snapshot_data_uses_points_cutoff_when_payout_unavailable(monkeypatch, tmp_path):
    class _FakeSport:
        name = "NBA"
        sheet_min_entry_fee = 25
        keyword = "%"

    class _FakePlayer:
        name = "A"
        pos = "PG"
        roster_pos = ["PG"]
        salary = 5000
        team_abbv = "LAL"
        game_info = "Final"
        matchup_info = "LAL@BOS"
        ownership = 0.2
        fpts = 12.0
        value = 2.4

    class _FakeUser:
        rank = 6
        player_id = "ek1"
        name = "vip1"
        pmr = "0"
        pts = 336.25

    class _FakeContestDb:
        def get_live_contest_candidates(self, *_args, **_kwargs):
            return []

        def get_contest_by_id(self, *_args, **_kwargs):
            return (123, "NBA Contest", 777, 50, "2026-02-14 01:00:00", 10, 1500)

        def get_contest_state(self, *_args, **_kwargs):
            return ("In Progress", 0)

        def get_contest_contract_metadata(self, *_args, **_kwargs):
            return (250000, 1500, 1, 114)

        def close(self):
            return None

    class _FakeDraftKings:
        def download_salary_csv(self, _sport, _draft_group, filename):
            path = tmp_path / "salary.csv"
            path.write_text("Position,Name,Salary\nPG,A,5000\n", encoding="utf-8")

        def get_leaderboard(self, *_args, **_kwargs):
            return {"leaderBoard": []}

        def download_contest_rows(self, *_args, **_kwargs):
            return [
                ["Rank", "EntryId", "EntryName", "TimeRemaining", "Points", "Lineup"],
                ["6", "ek1", "vip1", "0", "336.25", "PG A"],
            ]

        def get_vip_lineups(self, *_args, **_kwargs):
            return [{"user": "vip1", "entry_key": "ek1", "players": [{"slot": "PG", "name": "A"}]}]

    class _FakeResults:
        def __init__(self, *_args, **_kwargs):
            self.vip_list = [_FakeUser()]
            self.players = {"A": _FakePlayer()}
            self.users = [_FakeUser()]
            self.non_cashing_users = 0
            self.non_cashing_players = {}
            self.non_cashing_avg_pmr = 0.0
            self.min_rank = 50
            self.min_cash_pts = 325.25

    class _FakeTrainFinder:
        def __init__(self, _users):
            pass

        def get_users_above_salary_spent(self, _limit):
            return {}

    monkeypatch.setattr(snapshot_exporter, "_sport_choices", lambda: {"NBA": _FakeSport})
    monkeypatch.setattr(snapshot_exporter, "ContestDatabase", lambda _path: _FakeContestDb())
    monkeypatch.setattr(snapshot_exporter, "Draftkings", _FakeDraftKings)
    monkeypatch.setattr(snapshot_exporter, "Results", _FakeResults)
    monkeypatch.setattr(snapshot_exporter, "TrainFinder", _FakeTrainFinder)
    monkeypatch.setattr(snapshot_exporter, "load_vips", lambda: ["vip1"])
    monkeypatch.setattr(snapshot_exporter.state, "contests_db_path", lambda: tmp_path / "contests.db")
    monkeypatch.setattr(snapshot_exporter, "SALARY_DIR", str(tmp_path))

    snapshot = snapshot_exporter.collect_snapshot_data(sport="NBA", contest_id=123, standings_limit=10)
    assert snapshot["standings"][0].get("payout_cents") is None

    sport_payload = snapshot_exporter.build_dashboard_sport_snapshot(snapshot, "2026-02-14T02:00:00Z")
    contest = sport_payload["contests"][0]
    assert contest["standings"]["rows"][0]["payout_cents"] is None
    assert contest["standings"]["rows"][0]["is_cashing"] is True
    assert contest["vip_lineups"][0]["live"]["payout_cents"] is None
    assert contest["vip_lineups"][0]["live"]["is_cashing"] is True


def test_collect_snapshot_data_uses_winnings_cash_fallback_when_winning_value_missing(monkeypatch, tmp_path):
    class _FakeSport:
        name = "NBA"
        sheet_min_entry_fee = 25
        keyword = "%"

    class _FakePlayer:
        name = "A"
        pos = "PG"
        roster_pos = ["PG"]
        salary = 5000
        team_abbv = "LAL"
        game_info = "Final"
        matchup_info = "LAL@BOS"
        ownership = 0.2
        fpts = 12.0
        value = 2.4

    class _FakeUser:
        rank = 6
        player_id = "ek1"
        name = "vip1"
        pmr = "0"
        pts = 336.25

    class _FakeContestDb:
        def get_live_contest_candidates(self, *_args, **_kwargs):
            return []

        def get_contest_by_id(self, *_args, **_kwargs):
            return (123, "NBA Contest", 777, 50, "2026-02-14 01:00:00", 10, 1500)

        def get_contest_state(self, *_args, **_kwargs):
            return ("In Progress", 0)

        def get_contest_contract_metadata(self, *_args, **_kwargs):
            return (250000, 1500, 1, 114)

        def close(self):
            return None

    class _FakeDraftKings:
        def download_salary_csv(self, _sport, _draft_group, filename):
            path = tmp_path / "salary.csv"
            path.write_text("Position,Name,Salary\nPG,A,5000\n", encoding="utf-8")

        def get_leaderboard(self, *_args, **_kwargs):
            return {
                "leaderBoard": [
                    {
                        "entryKey": "ek1",
                        "winningValue": None,
                        "winnings": [
                            {"description": "Ticket", "value": 5},
                            {"description": "Cash", "value": 20.126},
                        ],
                    }
                ]
            }

        def download_contest_rows(self, *_args, **_kwargs):
            return [
                ["Rank", "EntryId", "EntryName", "TimeRemaining", "Points", "Lineup"],
                ["6", "ek1", "vip1", "0", "336.25", "PG A"],
            ]

        def get_vip_lineups(self, *_args, **_kwargs):
            return [{"user": "vip1", "entry_key": "ek1", "players": [{"slot": "PG", "name": "A"}]}]

    class _FakeResults:
        def __init__(self, *_args, **_kwargs):
            self.vip_list = [_FakeUser()]
            self.players = {"A": _FakePlayer()}
            self.users = [_FakeUser()]
            self.non_cashing_users = 0
            self.non_cashing_players = {}
            self.non_cashing_avg_pmr = 0.0
            self.min_rank = 50
            self.min_cash_pts = 325.25

    class _FakeTrainFinder:
        def __init__(self, _users):
            pass

        def get_users_above_salary_spent(self, _limit):
            return {}

    monkeypatch.setattr(snapshot_exporter, "_sport_choices", lambda: {"NBA": _FakeSport})
    monkeypatch.setattr(snapshot_exporter, "ContestDatabase", lambda _path: _FakeContestDb())
    monkeypatch.setattr(snapshot_exporter, "Draftkings", _FakeDraftKings)
    monkeypatch.setattr(snapshot_exporter, "Results", _FakeResults)
    monkeypatch.setattr(snapshot_exporter, "TrainFinder", _FakeTrainFinder)
    monkeypatch.setattr(snapshot_exporter, "load_vips", lambda: ["vip1"])
    monkeypatch.setattr(snapshot_exporter.state, "contests_db_path", lambda: tmp_path / "contests.db")
    monkeypatch.setattr(snapshot_exporter, "SALARY_DIR", str(tmp_path))

    snapshot = snapshot_exporter.collect_snapshot_data(sport="NBA", contest_id=123, standings_limit=10)
    assert snapshot["standings"][0]["payout_cents"] == 2013

    sport_payload = snapshot_exporter.build_dashboard_sport_snapshot(snapshot, "2026-02-14T02:00:00Z")
    contest = sport_payload["contests"][0]
    assert contest["standings"]["rows"][0]["payout_cents"] == 2013
    assert contest["standings"]["rows"][0]["is_cashing"] is True
    assert contest["vip_lineups"][0]["live"]["payout_cents"] == 2013
    assert contest["vip_lineups"][0]["live"]["is_cashing"] is True


def test_collect_snapshot_data_winning_value_precedence_over_winnings(monkeypatch, tmp_path):
    class _FakeSport:
        name = "NBA"
        sheet_min_entry_fee = 25
        keyword = "%"

    class _FakePlayer:
        name = "A"
        pos = "PG"
        roster_pos = ["PG"]
        salary = 5000
        team_abbv = "LAL"
        game_info = "Final"
        matchup_info = "LAL@BOS"
        ownership = 0.2
        fpts = 12.0
        value = 2.4

    class _FakeUser:
        rank = 6
        player_id = "ek1"
        name = "vip1"
        pmr = "0"
        pts = 336.25

    class _FakeContestDb:
        def get_live_contest_candidates(self, *_args, **_kwargs):
            return []

        def get_contest_by_id(self, *_args, **_kwargs):
            return (123, "NBA Contest", 777, 50, "2026-02-14 01:00:00", 10, 1500)

        def get_contest_state(self, *_args, **_kwargs):
            return ("In Progress", 0)

        def get_contest_contract_metadata(self, *_args, **_kwargs):
            return (250000, 1500, 1, 114)

        def close(self):
            return None

    class _FakeDraftKings:
        def download_salary_csv(self, _sport, _draft_group, filename):
            path = tmp_path / "salary.csv"
            path.write_text("Position,Name,Salary\nPG,A,5000\n", encoding="utf-8")

        def get_leaderboard(self, *_args, **_kwargs):
            return {
                "leaderBoard": [
                    {
                        "entryKey": "ek1",
                        "winningValue": 20,
                        "winnings": [{"description": "Cash", "value": 12}],
                    }
                ]
            }

        def download_contest_rows(self, *_args, **_kwargs):
            return [
                ["Rank", "EntryId", "EntryName", "TimeRemaining", "Points", "Lineup"],
                ["6", "ek1", "vip1", "0", "336.25", "PG A"],
            ]

        def get_vip_lineups(self, *_args, **_kwargs):
            return [{"user": "vip1", "entry_key": "ek1", "players": [{"slot": "PG", "name": "A"}]}]

    class _FakeResults:
        def __init__(self, *_args, **_kwargs):
            self.vip_list = [_FakeUser()]
            self.players = {"A": _FakePlayer()}
            self.users = [_FakeUser()]
            self.non_cashing_users = 0
            self.non_cashing_players = {}
            self.non_cashing_avg_pmr = 0.0
            self.min_rank = 50
            self.min_cash_pts = 325.25

    class _FakeTrainFinder:
        def __init__(self, _users):
            pass

        def get_users_above_salary_spent(self, _limit):
            return {}

    monkeypatch.setattr(snapshot_exporter, "_sport_choices", lambda: {"NBA": _FakeSport})
    monkeypatch.setattr(snapshot_exporter, "ContestDatabase", lambda _path: _FakeContestDb())
    monkeypatch.setattr(snapshot_exporter, "Draftkings", _FakeDraftKings)
    monkeypatch.setattr(snapshot_exporter, "Results", _FakeResults)
    monkeypatch.setattr(snapshot_exporter, "TrainFinder", _FakeTrainFinder)
    monkeypatch.setattr(snapshot_exporter, "load_vips", lambda: ["vip1"])
    monkeypatch.setattr(snapshot_exporter.state, "contests_db_path", lambda: tmp_path / "contests.db")
    monkeypatch.setattr(snapshot_exporter, "SALARY_DIR", str(tmp_path))

    snapshot = snapshot_exporter.collect_snapshot_data(sport="NBA", contest_id=123, standings_limit=10)
    assert snapshot["standings"][0]["payout_cents"] == 2000


def test_dashboard_contract_gate_discriminates_envelope_vs_raw_shape():
    raw_snapshot_out_shape = {
        "schema_version": 2,
        "snapshot_at": "2026-02-14T00:00:00Z",
        "generated_at": "2026-02-14T00:00:00Z",
        "contest": {},
        "selection": {},
        "vip_lineups": [],
        "standings": [],
    }
    envelope = {
        "schema_version": 2,
        "snapshot_at": "2026-02-14T00:00:00Z",
        "generated_at": "2026-02-14T00:00:00Z",
        "sports": {
            "nba": {
                "status": "ok",
                "updated_at": "2026-02-14T00:00:00Z",
                "players": [],
                "contests": [],
            }
        },
    }

    assert snapshot_exporter.is_dashboard_envelope(raw_snapshot_out_shape) is False
    assert snapshot_exporter.is_dashboard_envelope(envelope) is True
