import datetime
import json
import logging
from argparse import Namespace
from collections import OrderedDict
from pathlib import Path

from classes.sport import NFLSport

import dk_results.cli.db_main as db_main


def _salary_csv_text() -> str:
    return (
        "Position,ID,Name,ID2,Roster Position,Salary,Game Info,TeamAbbrev,AvgPoints\n"
        "QB,,Tom Brady,,QB,7000,NE@NYJ 1:00PM ET,NE,0\n"
        "RB,,Derrick Henry,,RB/FLEX,8000,TEN@IND 1:00PM ET,TEN,0\n"
    )


def _standings_rows() -> list[list[str]]:
    return [
        [
            "Rank",
            "EntryId",
            "EntryName",
            "TimeRemaining",
            "Points",
            "Lineup",
            "",
            "Player",
            "Roster Position",
            "%Drafted",
            "FPTS",
        ],
        [
            "1",
            "111",
            "UserA",
            "0",
            "120",
            "QB Tom Brady RB Derrick Henry",
            "",
            "",
            "",
            "",
            "",
        ],
        ["", "", "", "", "", "", "", "Tom Brady", "QB", "50.00%", "20"],
        ["", "", "", "", "", "", "", "", "", "", ""],
    ]


def _standings_rows_with_missing_vip_entry() -> list[list[str]]:
    return [
        [
            "Rank",
            "EntryId",
            "EntryName",
            "TimeRemaining",
            "Points",
            "Lineup",
            "",
            "Player",
            "Roster Position",
            "%Drafted",
            "FPTS",
        ],
        [
            "1",
            "111",
            "UserA",
            "0",
            "120",
            "QB Tom Brady RB Derrick Henry",
            "",
            "",
            "",
            "",
            "",
        ],
        [
            "2",
            "",
            "UserB",
            "0",
            "110",
            "QB Tom Brady RB Derrick Henry",
            "",
            "",
            "",
            "",
            "",
        ],
        ["", "", "", "", "", "", "", "Tom Brady", "QB", "50.00%", "20"],
    ]


class _FakeContestDb:
    def get_live_contest(self, *_args, **_kwargs):
        return (
            123,
            "Test Contest",
            999,
            1,
            "2026-02-14 01:00:00",
        )


class _FakeContestDbNoLive:
    def get_live_contest(self, *_args, **_kwargs):
        return None


class _FakeDraftkings:
    def download_salary_csv(self, _sport: str, _draft_group: int, filename: str) -> None:
        path = Path(filename)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_salary_csv_text(), encoding="utf-8")

    def download_contest_rows(self, *_args, **_kwargs):
        return _standings_rows()

    def get_vip_lineups(self, *_args, **_kwargs):
        return []


class _FakeDraftkingsNoStandings(_FakeDraftkings):
    def download_contest_rows(self, *_args, **_kwargs):
        return None


class _FakeDraftkingsWithVipLineups(_FakeDraftkings):
    def get_vip_lineups(self, *_args, **_kwargs):
        return [{"user": "UserA", "players": []}]


class _FakeDraftkingsFetchError(_FakeDraftkings):
    def get_vip_lineups(self, *_args, **_kwargs):
        raise RuntimeError("fetch failed")


class _FakeDraftkingsTrackVipEntries(_FakeDraftkings):
    captured_vip_entries: dict[str, dict[str, object] | str] = {}

    def download_contest_rows(self, *_args, **_kwargs):
        return _standings_rows_with_missing_vip_entry()

    def get_vip_lineups(self, *_args, **kwargs):
        type(self).captured_vip_entries = kwargs.get("vip_entries", {})
        return []


class _FakeSheet:
    def __init__(self):
        self.players = []

    def clear_standings(self):
        return None

    def write_players(self, values):
        self.players = list(values)

    def add_contest_details(self, *_args, **_kwargs):
        return None

    def add_last_updated(self, *_args, **_kwargs):
        return None

    def add_min_cash(self, *_args, **_kwargs):
        return None

    def clear_lineups(self):
        return None

    def write_vip_lineups(self, *_args, **_kwargs):
        return None

    def add_non_cashing_info(self, *_args, **_kwargs):
        return None

    def add_train_info(self, *_args, **_kwargs):
        return None

    def add_optimal_lineup(self, *_args, **_kwargs):
        return None


def _event_messages(caplog, event_name: str) -> list[str]:
    return [record.message for record in caplog.records if record.message.startswith(f"{event_name} ")]


def _parse_event_fields(message: str) -> dict[str, str]:
    parts = message.split()[1:]
    out: dict[str, str] = {}
    for part in parts:
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        out[key] = value
    return out


def test_process_sport_parses_player_stats_only_rows_and_skips_blank_users(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(db_main, "Draftkings", _FakeDraftkings)
    fake_sheet = _FakeSheet()
    monkeypatch.setattr(db_main, "build_dfs_sheet_service", lambda _sport: fake_sheet)
    monkeypatch.setattr(db_main, "load_vips", lambda: [])

    observed = {}

    def _capture_train(_sheet, results):
        observed["users"] = len(results.users)

    monkeypatch.setattr(db_main, "write_train_info", _capture_train)

    args = Namespace(nolineups=False)
    contest_id = db_main.process_sport(
        "NFL",
        {"NFL": NFLSport},
        _FakeContestDb(),
        datetime.datetime(2026, 2, 14, 12, 0, 0),
        args,
        [],
    )

    # Player-only standings row should update ownership/fpts, so Tom Brady appears in player output.
    assert any(row[1] == "Tom Brady" for row in fake_sheet.players)
    # Blank core row should not create phantom users in db_main path.
    assert observed["users"] == 1
    assert contest_id == 123


def test_process_sport_handles_no_live_contest(monkeypatch, caplog):
    with caplog.at_level(logging.INFO):
        contest_id = db_main.process_sport(
            "NFL",
            {"NFL": NFLSport},
            _FakeContestDbNoLive(),
            datetime.datetime(2026, 2, 14, 12, 0, 0),
            Namespace(nolineups=False),
            ["UserA"],
        )

    assert contest_id is None
    detection = _event_messages(caplog, "vip_detection")
    fetch = _event_messages(caplog, "vip_fetch")
    sheet_write = _event_messages(caplog, "vip_sheet_write")
    assert len(detection) == 1
    assert len(fetch) == 1
    assert len(sheet_write) == 1


def test_process_sport_emits_deterministic_vip_events_for_standings_skip(monkeypatch, tmp_path, caplog):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(db_main, "Draftkings", _FakeDraftkingsNoStandings)
    monkeypatch.setattr(db_main, "build_dfs_sheet_service", lambda _sport: _FakeSheet())

    args = Namespace(nolineups=False)
    with caplog.at_level(logging.INFO):
        contest_id = db_main.process_sport(
            "NFL",
            {"NFL": NFLSport},
            _FakeContestDb(),
            datetime.datetime(2026, 2, 14, 12, 0, 0),
            args,
            ["UserA"],
        )

    assert contest_id is None
    detection = _event_messages(caplog, "vip_detection")
    fetch = _event_messages(caplog, "vip_fetch")
    sheet_write = _event_messages(caplog, "vip_sheet_write")
    assert len(detection) == 1
    assert len(fetch) == 1
    assert len(sheet_write) == 1
    assert _parse_event_fields(detection[0])["reason"] == "standings_unavailable"
    assert _parse_event_fields(fetch[0])["attempted"] == "false"
    assert _parse_event_fields(sheet_write[0])["written"] == "false"


def test_process_sport_emits_fetch_error_reason_to_fetch_and_sheet_events(monkeypatch, tmp_path, caplog):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(db_main, "Draftkings", _FakeDraftkingsFetchError)
    monkeypatch.setattr(db_main, "build_dfs_sheet_service", lambda _sport: _FakeSheet())

    args = Namespace(nolineups=False)
    with caplog.at_level(logging.INFO):
        contest_id = db_main.process_sport(
            "NFL",
            {"NFL": NFLSport},
            _FakeContestDb(),
            datetime.datetime(2026, 2, 14, 12, 0, 0),
            args,
            ["UserA"],
        )

    assert contest_id == 123
    fetch = _event_messages(caplog, "vip_fetch")
    sheet_write = _event_messages(caplog, "vip_sheet_write")
    assert len(fetch) == 1
    assert len(sheet_write) == 1
    assert _parse_event_fields(fetch[0])["reason"] == "fetch_error"
    assert _parse_event_fields(sheet_write[0])["reason"] == "fetch_error"
    assert _parse_event_fields(fetch[0])["attempted"] == "true"
    assert _parse_event_fields(sheet_write[0])["written"] == "false"


def test_vip_fetch_requested_uses_filtered_entry_keys(monkeypatch, tmp_path, caplog):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(db_main, "Draftkings", _FakeDraftkingsTrackVipEntries)
    monkeypatch.setattr(db_main, "build_dfs_sheet_service", lambda _sport: _FakeSheet())
    _FakeDraftkingsTrackVipEntries.captured_vip_entries = {}

    args = Namespace(nolineups=False)
    with caplog.at_level(logging.INFO):
        contest_id = db_main.process_sport(
            "NFL",
            {"NFL": NFLSport},
            _FakeContestDb(),
            datetime.datetime(2026, 2, 14, 12, 0, 0),
            args,
            ["UserA", "UserB"],
        )

    assert contest_id == 123
    assert len(_FakeDraftkingsTrackVipEntries.captured_vip_entries) == 1
    fetch = _event_messages(caplog, "vip_fetch")
    assert len(fetch) == 1
    assert _parse_event_fields(fetch[0])["requested"] == "1"


def test_process_sport_emits_vip_events_when_results_build_fails(monkeypatch, tmp_path, caplog):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(db_main, "Draftkings", _FakeDraftkings)
    monkeypatch.setattr(db_main, "build_dfs_sheet_service", lambda _sport: _FakeSheet())
    monkeypatch.setattr(db_main, "_build_results", lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")))

    args = Namespace(nolineups=False)
    with caplog.at_level(logging.INFO):
        contest_id = db_main.process_sport(
            "NFL",
            {"NFL": NFLSport},
            _FakeContestDb(),
            datetime.datetime(2026, 2, 14, 12, 0, 0),
            args,
            ["UserA"],
        )

    assert contest_id is None
    detection = _event_messages(caplog, "vip_detection")
    fetch = _event_messages(caplog, "vip_fetch")
    sheet_write = _event_messages(caplog, "vip_sheet_write")
    assert len(detection) == 1
    assert len(fetch) == 1
    assert len(sheet_write) == 1
    assert _parse_event_fields(detection[0])["reason"] == "results_unavailable"
    assert _parse_event_fields(fetch[0])["reason"] == "results_unavailable"
    assert _parse_event_fields(sheet_write[0])["reason"] == "results_unavailable"


def test_process_sport_logs_optimizer_skip(monkeypatch, tmp_path, caplog):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(db_main, "Draftkings", _FakeDraftkings)
    monkeypatch.setattr(db_main, "build_dfs_sheet_service", lambda _sport: _FakeSheet())

    args = Namespace(nolineups=False)
    with caplog.at_level(logging.INFO):
        db_main.process_sport(
            "NFL",
            {"NFL": NFLSport},
            _FakeContestDb(),
            datetime.datetime(2026, 2, 14, 12, 0, 0),
            args,
            ["UserA"],
        )

    assert "Skipping optimal lineup for NFL" in caplog.text


def test_process_sport_emits_deterministic_vip_events_on_happy_path(monkeypatch, tmp_path, caplog):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(db_main, "Draftkings", _FakeDraftkingsWithVipLineups)
    monkeypatch.setattr(db_main, "build_dfs_sheet_service", lambda _sport: _FakeSheet())

    args = Namespace(nolineups=False)
    with caplog.at_level(logging.INFO):
        contest_id = db_main.process_sport(
            "NFL",
            {"NFL": NFLSport},
            _FakeContestDb(),
            datetime.datetime(2026, 2, 14, 12, 0, 0),
            args,
            ["UserA"],
        )

    assert contest_id == 123
    detection = _event_messages(caplog, "vip_detection")
    fetch = _event_messages(caplog, "vip_fetch")
    sheet_write = _event_messages(caplog, "vip_sheet_write")
    assert len(detection) == 1
    assert len(fetch) == 1
    assert len(sheet_write) == 1

    detection_fields = _parse_event_fields(detection[0])
    fetch_fields = _parse_event_fields(fetch[0])
    sheet_fields = _parse_event_fields(sheet_write[0])
    assert detection_fields["requested"] == "1"
    assert detection_fields["found"] == "1"
    assert detection_fields["attempted"] == "true"
    assert fetch_fields["requested"] == "1"
    assert fetch_fields["fetched"] == "1"
    assert fetch_fields["attempted"] == "true"
    assert sheet_fields["written"] == "true"
    assert sheet_fields["lineups"] == "1"


def test_vip_event_compatibility_mode(monkeypatch, tmp_path, caplog):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DK_VIP_EVENT_COMPAT", "1")
    monkeypatch.setattr(db_main, "Draftkings", _FakeDraftkingsWithVipLineups)
    monkeypatch.setattr(db_main, "build_dfs_sheet_service", lambda _sport: _FakeSheet())

    args = Namespace(nolineups=False)
    with caplog.at_level(logging.INFO):
        db_main.process_sport(
            "NFL",
            {"NFL": NFLSport},
            _FakeContestDb(),
            datetime.datetime(2026, 2, 14, 12, 0, 0),
            args,
            ["UserA"],
        )

    assert len(_event_messages(caplog, "vip_detection_summary")) == 1
    assert len(_event_messages(caplog, "vip_lineups_fetch")) == 1
    assert len(_event_messages(caplog, "vip_lineups_summary")) == 1
    assert "remove_after=2026-04-30" in caplog.text


def test_main_snapshot_out_writes_opt_in_envelope(monkeypatch, tmp_path):
    out = tmp_path / "snapshot.json"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(db_main, "load_dotenv", lambda: None)
    monkeypatch.setattr(db_main, "load_and_apply_settings", lambda: None)
    monkeypatch.setattr(db_main.state, "contests_db_path", lambda: tmp_path / "contests.db")
    monkeypatch.setattr(db_main, "ContestDatabase", lambda _path: object())
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
    monkeypatch.setattr(
        db_main,
        "process_sport",
        lambda sport_name, *_args, **_kwargs: 111 if sport_name == "NFL" else 222,
    )

    def _fake_snapshot(*, sport: str, contest_id: int | None, standings_limit: int):
        return {
            "sport": sport,
            "selection": {"selected_contest_id": contest_id},
            "truncation": {"limit": standings_limit},
            "metadata": {"warnings": [], "missing_fields": []},
        }

    monkeypatch.setattr(db_main, "build_snapshot", _fake_snapshot)

    db_main.main()

    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 2
    assert sorted(payload["sports"].keys()) == ["golf", "nfl"]
    assert payload["sports"]["nfl"]["selection"]["selected_contest_id"] == "111"
    assert payload["sports"]["golf"]["truncation"]["limit"] == 123
    assert payload["generated_at"].endswith("Z")
    assert payload["snapshot_at"].endswith("Z")


def test_main_verbose_enables_debug_without_mutating_log_level_env(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("LOG_LEVEL", "INFO")
    monkeypatch.setattr(db_main, "load_dotenv", lambda: None)
    monkeypatch.setattr(db_main, "load_and_apply_settings", lambda: None)
    monkeypatch.setattr(db_main.state, "contests_db_path", lambda: tmp_path / "contests.db")
    monkeypatch.setattr(db_main, "ContestDatabase", lambda _path: object())
    monkeypatch.setattr(db_main, "load_vips", lambda: [])
    monkeypatch.setattr(db_main, "process_sport", lambda *_args, **_kwargs: None)
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
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(db_main, "load_dotenv", lambda: None)
    monkeypatch.setattr(db_main, "load_and_apply_settings", lambda: None)
    monkeypatch.setattr(db_main.state, "contests_db_path", lambda: tmp_path / "contests.db")
    monkeypatch.setattr(db_main, "ContestDatabase", lambda _path: object())
    monkeypatch.setattr(db_main, "load_vips", lambda: [])
    monkeypatch.setattr(db_main, "process_sport", lambda *_args, **_kwargs: None)

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
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(db_main, "load_dotenv", lambda: None)
    monkeypatch.setattr(db_main, "load_and_apply_settings", lambda: None)
    monkeypatch.setattr(db_main.state, "contests_db_path", lambda: tmp_path / "contests.db")
    monkeypatch.setattr(db_main, "ContestDatabase", lambda _path: object())
    monkeypatch.setattr(db_main, "load_vips", lambda: [])
    monkeypatch.setattr(db_main, "process_sport", lambda *_args, **_kwargs: None)

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
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(db_main, "load_dotenv", lambda: None)
    monkeypatch.setattr(db_main, "load_and_apply_settings", lambda: None)
    monkeypatch.setattr(db_main.state, "contests_db_path", lambda: tmp_path / "contests.db")
    monkeypatch.setattr(db_main, "ContestDatabase", lambda _path: object())

    calls = {"load_vips": 0}

    def _load_vips_once():
        calls["load_vips"] += 1
        return ["UserA"]

    process_vip_args: list[list[str]] = []

    def _fake_process_sport(_sport_name, _choices, _db, _now, _args, vips):
        process_vip_args.append(list(vips))
        return None

    monkeypatch.setattr(db_main, "load_vips", _load_vips_once)
    monkeypatch.setattr(db_main, "process_sport", _fake_process_sport)
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
    assert process_vip_args == [["UserA"], ["UserA"]]


def test_write_snapshot_payload_is_byte_stable(tmp_path):
    out = tmp_path / "stable.json"
    payload = OrderedDict(
        [
            ("snapshot_at", "2026-01-01T00:00:00Z"),
            ("sports", {"nfl": {"b": 2, "a": 1}}),
            ("schema_version", 2),
            ("generated_at", "2026-01-01T00:00:00Z"),
        ]
    )

    db_main.write_snapshot_payload(out, payload)

    assert out.read_text(encoding="utf-8") == (
        "{\n"
        '  "generated_at":"2026-01-01T00:00:00Z",\n'
        '  "schema_version":2,\n'
        '  "snapshot_at":"2026-01-01T00:00:00Z",\n'
        '  "sports":{\n'
        '    "nfl":{\n'
        '      "a":1,\n'
        '      "b":2\n'
        "    }\n"
        "  }\n"
        "}\n"
    )
