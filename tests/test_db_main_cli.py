"""db_main.main and the snapshot payload writer and builder."""

import json
import logging
from argparse import Namespace
from collections import OrderedDict

import dk_results.cli.db_main as db_main
from dk_results.sport_processor import (
    NoLiveContestError,
)


def test_main_snapshot_out_writes_opt_in_envelope(monkeypatch, tmp_path):
    out = tmp_path / "snapshot.json"
    monkeypatch.setattr(db_main, "load_and_apply_settings", lambda: None)
    monkeypatch.setattr(db_main.state, "contests_db_path", lambda: tmp_path / "contests.db")
    monkeypatch.setattr(db_main, "ContestDatabase", lambda _path: object())
    monkeypatch.setattr(db_main, "DraftKings", lambda: object())
    monkeypatch.setattr(db_main, "load_vips", lambda: [])
    monkeypatch.setattr(
        db_main.argparse.ArgumentParser,
        "parse_args",
        lambda _self: Namespace(
            sport=["NFL", "GOLF"],
            nolineups=False,
            verbose=None,
            snapshot_out=str(out),
            standings_limit=123,
        ),
    )

    class _FakeSportProcessor:
        def __init__(self, **kwargs):
            pass

        def run(self, sport_name, sport_cls):
            return 111 if sport_name == "NFL" else 222

    monkeypatch.setattr(db_main, "SportProcessor", _FakeSportProcessor)

    def _fake_snapshot(selected_contests, *, standings_limit: int, generated_at=None, producer_commit=None):
        assert selected_contests == {"NFL": 111, "GOLF": 222}
        return {
            "schema_version": 3,
            "snapshot_at": generated_at or "2026-02-14T10:00:00Z",
            "generated_at": generated_at or "2026-02-14T10:00:00Z",
            "sports": {
                "nfl": {"primary_contest": {"contest_id": "111"}, "contests": [{}]},
                "golf": {"contests": [{}]},
            },
        }

    monkeypatch.setattr(db_main, "build_snapshot_v3_envelope", _fake_snapshot)

    db_main.main()

    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 3
    assert sorted(payload["sports"].keys()) == ["golf", "nfl"]
    assert payload["sports"]["nfl"]["primary_contest"]["contest_id"] == "111"
    assert len(payload["sports"]["golf"]["contests"]) == 1
    assert payload["generated_at"].endswith("Z")
    assert payload["snapshot_at"].endswith("Z")


def test_main_snapshot_out_skips_and_preserves_existing_output_when_no_contests(monkeypatch, tmp_path):
    out = tmp_path / "snapshot.json"
    original = '{"schema_version":3,"sports":{"nba":{}}}\n'
    out.write_text(original, encoding="utf-8")
    monkeypatch.setattr(db_main, "load_and_apply_settings", lambda: None)
    monkeypatch.setattr(db_main.state, "contests_db_path", lambda: tmp_path / "contests.db")
    monkeypatch.setattr(db_main, "ContestDatabase", lambda _path: object())
    monkeypatch.setattr(db_main, "DraftKings", lambda: object())
    monkeypatch.setattr(db_main, "load_vips", lambda: [])
    monkeypatch.setattr(
        db_main.argparse.ArgumentParser,
        "parse_args",
        lambda _self: Namespace(
            sport=["NFL"],
            nolineups=False,
            verbose=False,
            snapshot_out=str(out),
            standings_limit=123,
        ),
    )

    class _FakeSportProcessor:
        def __init__(self, **kwargs):
            pass

        def run(self, sport_name, sport_cls):
            raise NoLiveContestError("none")

    monkeypatch.setattr(db_main, "SportProcessor", _FakeSportProcessor)
    db_main.main()

    assert out.read_text(encoding="utf-8") == original


def test_main_verbose_enables_debug_without_mutating_log_level_env(monkeypatch, tmp_path):
    monkeypatch.setenv("LOG_LEVEL", "INFO")
    monkeypatch.setattr(db_main, "load_and_apply_settings", lambda: None)
    monkeypatch.setattr(db_main.state, "contests_db_path", lambda: tmp_path / "contests.db")
    monkeypatch.setattr(db_main, "ContestDatabase", lambda _path: object())
    monkeypatch.setattr(db_main, "DraftKings", lambda: object())
    monkeypatch.setattr(db_main, "load_vips", lambda: [])

    class _FakeSportProcessor:
        def __init__(self, **kwargs):
            pass

        def run(self, sport_name, sport_cls):
            return None

    monkeypatch.setattr(db_main, "SportProcessor", _FakeSportProcessor)
    monkeypatch.setattr(
        db_main.argparse.ArgumentParser,
        "parse_args",
        lambda _self: Namespace(
            sport=["NFL"],
            nolineups=False,
            verbose=True,
            snapshot_out=None,
            standings_limit=123,
        ),
    )

    root = logging.getLogger()
    root.setLevel(logging.WARNING)
    root.handlers.clear()

    db_main.main()

    assert root.level == logging.DEBUG
    assert db_main.os.environ["LOG_LEVEL"] == "INFO"


def test_main_verbose_flag_is_boolean(monkeypatch, tmp_path):
    monkeypatch.setattr(db_main, "load_and_apply_settings", lambda: None)
    monkeypatch.setattr(db_main.state, "contests_db_path", lambda: tmp_path / "contests.db")
    monkeypatch.setattr(db_main, "ContestDatabase", lambda _path: object())
    monkeypatch.setattr(db_main, "DraftKings", lambda: object())
    monkeypatch.setattr(db_main, "load_vips", lambda: [])

    class _FakeSportProcessor:
        def __init__(self, **kwargs):
            pass

        def run(self, sport_name, sport_cls):
            return None

    monkeypatch.setattr(db_main, "SportProcessor", _FakeSportProcessor)

    observed: dict[str, str | None] = {"action": None}
    original_add_argument = db_main.argparse.ArgumentParser.add_argument

    def _capture_add_argument(parser, *names, **kwargs):
        if "--verbose" in names:
            observed["action"] = kwargs.get("action")
        return original_add_argument(parser, *names, **kwargs)

    monkeypatch.setattr(db_main.argparse.ArgumentParser, "add_argument", _capture_add_argument)
    monkeypatch.setattr(
        db_main.argparse.ArgumentParser,
        "parse_args",
        lambda _self: Namespace(
            sport=["NFL"],
            nolineups=False,
            verbose=False,
            snapshot_out=None,
            standings_limit=123,
        ),
    )

    db_main.main()

    assert observed["action"] == "store_true"


def test_main_verbose_uses_explicit_logging_override(monkeypatch, tmp_path):
    monkeypatch.setattr(db_main, "load_and_apply_settings", lambda: None)
    monkeypatch.setattr(db_main.state, "contests_db_path", lambda: tmp_path / "contests.db")
    monkeypatch.setattr(db_main, "ContestDatabase", lambda _path: object())
    monkeypatch.setattr(db_main, "DraftKings", lambda: object())
    monkeypatch.setattr(db_main, "load_vips", lambda: [])

    class _FakeSportProcessor:
        def __init__(self, **kwargs):
            pass

        def run(self, sport_name, sport_cls):
            return None

    monkeypatch.setattr(db_main, "SportProcessor", _FakeSportProcessor)

    observed: list[str | int | None] = []
    monkeypatch.setattr(db_main, "configure_logging", lambda level_override=None: observed.append(level_override))
    monkeypatch.setattr(
        db_main.argparse.ArgumentParser,
        "parse_args",
        lambda _self: Namespace(
            sport=["NFL"],
            nolineups=False,
            verbose=True,
            snapshot_out=None,
            standings_limit=123,
        ),
    )

    db_main.main()

    assert observed == ["DEBUG"]


def test_main_loads_vips_once_per_invocation(monkeypatch, tmp_path):
    monkeypatch.setattr(db_main, "load_and_apply_settings", lambda: None)
    monkeypatch.setattr(db_main.state, "contests_db_path", lambda: tmp_path / "contests.db")
    monkeypatch.setattr(db_main, "ContestDatabase", lambda _path: object())
    monkeypatch.setattr(db_main, "DraftKings", lambda: object())

    calls = {"load_vips": 0}

    def _load_vips_once():
        calls["load_vips"] += 1
        return ["UserA"]

    captured_vips: list[str] = []
    run_sports: list[str] = []

    class _FakeSportProcessor:
        def __init__(self, *, vips, **kwargs):
            captured_vips.extend(vips)

        def run(self, sport_name, sport_cls):
            run_sports.append(sport_name)
            return None

    monkeypatch.setattr(db_main, "load_vips", _load_vips_once)
    monkeypatch.setattr(db_main, "SportProcessor", _FakeSportProcessor)
    monkeypatch.setattr(
        db_main.argparse.ArgumentParser,
        "parse_args",
        lambda _self: Namespace(
            sport=["NFL", "GOLF"],
            nolineups=False,
            verbose=False,
            snapshot_out=None,
            standings_limit=123,
        ),
    )

    db_main.main()

    assert calls["load_vips"] == 1
    assert captured_vips == ["UserA"]
    assert run_sports == ["NFL", "GOLF"]


def test_write_snapshot_payload_is_byte_stable(tmp_path):
    out = tmp_path / "stable.json"
    payload = OrderedDict(
        [
            ("snapshot_at", "2026-01-01T00:00:00Z"),
            ("sports", {"nfl": {"b": 2, "a": 1}}),
            ("schema_version", 3),
            ("generated_at", "2026-01-01T00:00:00Z"),
        ]
    )

    db_main.write_snapshot_payload(out, payload)

    assert out.read_text(encoding="utf-8") == (
        "{\n"
        '  "generated_at":"2026-01-01T00:00:00Z",\n'
        '  "schema_version":3,\n'
        '  "snapshot_at":"2026-01-01T00:00:00Z",\n'
        '  "sports":{\n'
        '    "nfl":{\n'
        '      "a":1,\n'
        '      "b":2\n'
        "    }\n"
        "  }\n"
        "}\n"
    )


def test_build_snapshot_payload_forwards_the_producer_commit_to_the_envelope_builder(monkeypatch):
    captured: dict = {}

    def _fake(selected_contests, *, standings_limit, producer_commit):
        captured.update(selected=selected_contests, producer_commit=producer_commit)
        return {}

    monkeypatch.setattr(db_main, "build_snapshot_v3_envelope", _fake)
    sha = "0123456789abcdef0123456789abcdef01234567"

    db_main.build_snapshot_payload({"NBA": 1}, producer_commit=sha)

    assert captured == {"selected": {"NBA": 1}, "producer_commit": sha}
