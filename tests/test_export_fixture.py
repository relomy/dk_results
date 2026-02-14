import datetime
import hashlib
import json
from argparse import Namespace

import pytest

import commands.export_fixture as export_command
import export_fixture
import services.snapshot_exporter as snapshot_exporter


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
    services_dir = repo_root / "services"
    services_dir.mkdir(parents=True)
    (repo_root / "vips.yaml").write_text("- vip_one\n- vip_two\n", encoding="utf-8")
    monkeypatch.setattr(
        snapshot_exporter,
        "__file__",
        str(services_dir / "snapshot_exporter.py"),
    )

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
            "contest": {"contest_id": "42", "is_primary": True},
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


def test_run_export_bundle_writes_two_sports(monkeypatch, tmp_path):
    monkeypatch.setattr(export_command, "configure_runtime", lambda: None)

    def _fake_build_snapshot(*, sport: str, contest_id: int | None, standings_limit: int):
        return {
            "snapshot_version": "v1",
            "snapshot_generated_at_utc": "2026-02-14T10:00:00Z",
            "sport": sport,
            "contest": {"contest_id": contest_id, "is_primary": True},
            "selection": {"selected_contest_id": contest_id, "reason": {}},
            "candidates": [],
            "cash_line": {},
            "vip_lineups": [],
            "players": [],
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
                "contest_id": 188080404,
                "name": "NBA Single Entry",
                "entries": 1000,
                "positions_paid": 200,
                "is_primary": True,
            },
            "selection": {
                "selected_contest_id": 188080404,
                "reason": {"mode": "explicit_id"},
            },
            "cash_line": {"cutoff_type": "positions_paid", "rank": 200, "points": 250.5},
            "vip_lineups": [{"username": "vip1", "entry_key": "1", "rank": 2, "pts": 249.0, "pmr": 12.0, "lineup": ["A", "B"]}],
            "players": [{"name": "A"}, {"name": "B"}],
            "ownership": {
                "ownership_remaining_total_pct": 123.4,
                "top_remaining_players": [{"player_name": "A", "ownership_remaining_pct": 40.0}],
            },
            "train_clusters": [{"cluster_id": "abc123", "user_count": 2, "rank": 3, "points": 249.0, "pmr": 10.0, "lineup_signature": "A|B", "entry_keys": ["1"]}],
            "standings": [{"entry_key": "1", "username": "u1", "rank": 2, "points": 249.0, "pmr": "12.0", "ownership_remaining_total_pct": "33.0"}],
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
            "contest": {"contest_id": contest_id, "name": f"{sport} contest", "is_primary": True},
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
            "vip_lineups": [
                {"entry_key": "vip-1", "pts": 102.5, "rank": 8, "username": "vip"}
            ],
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

    assert metrics["cutoff_points"] == 100.0
    assert metrics["per_vip"][0]["points_delta"] == 2.5
    assert metrics["per_vip"][0]["rank_delta"] == 2


def test_vip_lineups_support_user_and_players_shape(monkeypatch, tmp_path):
    monkeypatch.setattr(export_command, "configure_runtime", lambda: None)
    monkeypatch.setattr(
        export_command,
        "build_snapshot",
        lambda **_kwargs: {
            "snapshot_version": "v1",
            "snapshot_generated_at_utc": "2026-02-14T10:00:00Z",
            "sport": "NBA",
            "contest": {"contest_id": 1, "name": "x", "is_primary": True},
            "selection": {"selected_contest_id": 1, "reason": {"mode": "explicit_id"}},
            "cash_line": {"cutoff_type": "rank", "rank": 10, "points": 100.0},
            "players": [{"name": "Alpha"}, {"name": "Beta"}],
            "ownership": {"ownership_remaining_total_pct": 1.0, "top_remaining_players": []},
            "standings": [{"entry_key": "777", "username": "vip_user", "rank": "5", "points": "110.0", "pmr": "0", "ownership_remaining_total_pct": "20.0", "payout_cents": 1500}],
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
    rc = export_command.run_export_fixture(
        Namespace(sport="NBA", contest_id=1, out=str(out), standings_limit=100)
    )
    payload = json.loads(out.read_text(encoding="utf-8"))
    vip = payload["sports"]["nba"]["contests"][0]["vip_lineups"][0]

    assert rc == 0
    assert vip["display_name"] == "vip_user"
    assert vip["entry_key"] == "777"
    assert vip["slots"][0]["player_name"] == "Alpha"
    assert vip["slots"][1]["player_name"] == "Beta"
    assert isinstance(vip["live"]["pmr"], float)
    assert isinstance(vip["live"]["current_rank"], int)
    assert vip["live"]["is_cashing"] is True
    assert vip["live"]["payout_cents"] == 1500


def test_vip_entry_key_backfill_requires_unique_display_name(monkeypatch, tmp_path):
    monkeypatch.setattr(export_command, "configure_runtime", lambda: None)
    monkeypatch.setattr(
        export_command,
        "build_snapshot",
        lambda **_kwargs: {
            "snapshot_version": "v1",
            "snapshot_generated_at_utc": "2026-02-14T10:00:00Z",
            "sport": "NBA",
            "contest": {"contest_id": 1, "name": "x", "is_primary": True},
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
    rc = export_command.run_export_fixture(
        Namespace(sport="NBA", contest_id=1, out=str(out), standings_limit=100)
    )
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
            "contest": {"contest_id": 1, "name": "x", "is_primary": True},
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
    rc = export_command.run_export_fixture(
        Namespace(sport="NBA", contest_id=1, out=str(out), standings_limit=100)
    )
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
