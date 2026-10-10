import datetime
import json
import logging
from argparse import Namespace
from collections import OrderedDict
from pathlib import Path
from types import SimpleNamespace

import pytest

import dk_results.cli.db_main as db_main
from dk_results.domain.sport import NFLSport
from dk_results.persistence.contestdatabase import VipCashStatus
from dk_results.sport_processor import (
    NoLiveContestError,
    SportProcessor,
    SportProcessorConfig,
    StandingsUnavailableError,
    StandsParseError,
)


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
    def __init__(self):
        self.cash_lines: dict[int, tuple[int | None, float | None]] = {}
        self.vip_statuses: dict[int, list] = {}

    def get_live_contest(self, *_args, **_kwargs):
        return (
            123,
            "Test Contest",
            999,
            1,
            "2026-02-14 01:00:00",
        )

    def set_cash_line(self, dk_id, rank, points):
        self.cash_lines[dk_id] = (rank, points)

    def replace_vip_cash_status(self, dk_id, statuses):
        self.vip_statuses[dk_id] = statuses


class _FakeContestDbNoLive:
    def get_live_contest(self, *_args, **_kwargs):
        return None


class _FakeContestDbNoPositionsPaid(_FakeContestDb):
    def get_live_contest(self, *_args, **_kwargs):
        return (
            123,
            "Test Contest",
            999,
            None,
            "2026-02-14 01:00:00",
        )


class _FakeContestDbNoDraftGroup(_FakeContestDb):
    def get_live_contest(self, *_args, **_kwargs):
        return (
            123,
            "Test Contest",
            None,
            1,
            "2026-02-14 01:00:00",
        )


class _FakeDraftKings:
    def download_salary_csv(self, _sport: str, _draft_group: int, filename: str) -> None:
        path = Path(filename)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_salary_csv_text(), encoding="utf-8")

    def download_contest_rows(self, *_args, **_kwargs):
        return _standings_rows()

    def clone_auth_to(self, _session) -> None:
        pass


class _FakeVipLineup:
    def to_dict(self) -> dict:
        return {
            "user": "UserA",
            "entry_key": "ek1",
            "rank": "1",
            "pts": "336.25",
            "pmr": "0",
            "total_salary": 0,
            "players": [],
        }


class _FakeDraftKingsNoStandings(_FakeDraftKings):
    def download_contest_rows(self, *_args, **_kwargs):
        return None


class _FakeDraftKingsTrackVipEntries(_FakeDraftKings):
    captured_vip_entries: dict = {}

    def download_contest_rows(self, *_args, **_kwargs):
        return _standings_rows_with_missing_vip_entry()


class _FakeSheet:
    def __init__(self):
        self.players = []

    def clear_standings(self):
        return None

    def write_players(self, values, format_plan=()):
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


def _make_processor(
    db,
    vips,
    *,
    dk=None,
    sheet=None,
    nolineups: bool = False,
    salary_dir: str = "",
    bonus_sender=None,
) -> SportProcessor:
    if dk is None:
        dk = _FakeDraftKings()
    if sheet is None:
        sheet = _FakeSheet()
    return SportProcessor(
        contest_db=db,
        dk=dk,
        sheet_factory=lambda _sport: sheet,
        bonus_sender=bonus_sender,
        config=SportProcessorConfig(
            salary_dir=salary_dir,
            contest_dir=".",
            cookies_file=".",
            write_optimal_lineup=nolineups,
        ),
        now=datetime.datetime(2026, 2, 14, 12, 0, 0),
        vips=vips,
    )


def test_process_sport_parses_player_stats_only_rows_and_skips_blank_users(monkeypatch, tmp_path):
    fake_sheet = _FakeSheet()
    observed = {}

    def _capture_train(self, sheet, results):
        observed["users"] = len(results.users)

    monkeypatch.setattr(SportProcessor, "_write_train_info", _capture_train)
    processor = _make_processor(_FakeContestDb(), vips=[], sheet=fake_sheet, salary_dir=str(tmp_path))
    contest_id = processor.run("NFL", NFLSport)

    # Player-only standings row should update ownership/fpts, so Tom Brady appears in player output.
    assert any(row[1] == "Tom Brady" for row in fake_sheet.players)
    # Blank core row should not create phantom users in db_main path.
    assert observed["users"] == 1
    assert contest_id == 123


def test_process_sport_persists_cash_line_and_vip_status(tmp_path):
    db = _FakeContestDb()
    processor = _make_processor(db, vips=["UserA"], salary_dir=str(tmp_path))
    contest_id = processor.run("NFL", NFLSport)

    assert contest_id == 123
    assert db.cash_lines[123] == (1, 120.0)
    assert db.vip_statuses[123] == [VipCashStatus(vip_name="UserA", rank=1, points=120.0)]


class _FakeContestDbTwoPaid(_FakeContestDb):
    def get_live_contest(self, *_args, **_kwargs):
        return (123, "Test Contest", 999, 2, "2026-02-14 01:00:00")


class _FakeDraftKingsTiedAtTop(_FakeDraftKings):
    def download_contest_rows(self, *_args, **_kwargs):
        both = "QB Tom Brady RB Derrick Henry"
        return [
            ["Rank", "EntryId", "EntryName", "TimeRemaining", "Points", "Lineup"],
            ["1", "111", "UserA", "0", "120", both],
            ["2", "222", "UserB", "0", "120", both],
            ["3", "333", "UserC", "30", "100", "RB Derrick Henry"],
        ]


class _CapturingSheet(_FakeSheet):
    def __init__(self):
        super().__init__()
        self.non_cashing_info = None

    def add_non_cashing_info(self, info):
        self.non_cashing_info = info


def test_process_sport_sheet_non_cashing_block_excludes_rows_tied_inside_the_cash_line(tmp_path):
    sheet = _CapturingSheet()
    processor = _make_processor(
        _FakeContestDbTwoPaid(), vips=[], dk=_FakeDraftKingsTiedAtTop(), sheet=sheet, salary_dir=str(tmp_path)
    )
    processor.run("NFL", NFLSport)

    assert sheet.non_cashing_info == [
        ["Non-Cashing Info", ""],
        ["Users not cashing", 1],
        ["Avg PMR Remaining", 30.0],
        ["Top 10 Own% Remaining", ""],
        ["Derrick Henry", 1.0],
    ]


def test_process_sport_persists_none_cash_line_when_positions_paid_missing(tmp_path):
    db = _FakeContestDbNoPositionsPaid()
    processor = _make_processor(db, vips=["UserA"], salary_dir=str(tmp_path))
    processor.run("NFL", NFLSport)

    assert db.cash_lines[123] == (None, None)
    # A VIP rank means nothing without a cash line to compare it against, so no
    # rows should be persisted until the cash line itself is known.
    assert db.vip_statuses[123] == []


def test_process_sport_handles_no_live_contest(caplog):
    processor = _make_processor(_FakeContestDbNoLive(), vips=["UserA"])
    with caplog.at_level(logging.DEBUG):
        with pytest.raises(NoLiveContestError):
            processor.run("NFL", NFLSport)

    assert len(_event_messages(caplog, "vip_detection")) == 0
    assert len(_event_messages(caplog, "vip_fetch")) == 0
    assert len(_event_messages(caplog, "vip_sheet_write")) == 0
    # Idle sports are the normal case on a 5-minute schedule: the processor stays
    # silent and select_live_contests reports them in one line.
    assert [r for r in caplog.records if r.levelno >= logging.WARNING] == []
    assert not [r for r in caplog.records if "no live contests" in r.getMessage().lower()]


def test_process_sport_emits_no_vip_events_for_standings_skip(tmp_path, caplog):
    processor = _make_processor(
        _FakeContestDb(),
        vips=["UserA"],
        dk=_FakeDraftKingsNoStandings(),
        salary_dir=str(tmp_path),
    )
    with caplog.at_level(logging.INFO):
        with pytest.raises(StandingsUnavailableError):
            processor.run("NFL", NFLSport)

    assert len(_event_messages(caplog, "vip_detection")) == 0
    assert len(_event_messages(caplog, "vip_fetch")) == 0
    assert len(_event_messages(caplog, "vip_sheet_write")) == 0


def test_process_sport_emits_fetch_error_reason_to_fetch_and_sheet_events(monkeypatch, tmp_path, caplog):
    monkeypatch.setattr(
        "dk_results.sport_processor.fetch_vip_lineups",
        lambda *_a, **_kw: (_ for _ in ()).throw(RuntimeError("fetch failed")),
    )
    processor = _make_processor(_FakeContestDb(), vips=["UserA"], salary_dir=str(tmp_path))
    with caplog.at_level(logging.INFO):
        contest_id = processor.run("NFL", NFLSport)

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
    captured: dict = {}

    def _capture_fetch(*_args, vip_entries=None, **_kw):
        captured["vip_entries"] = vip_entries or {}
        return []

    monkeypatch.setattr("dk_results.sport_processor.fetch_vip_lineups", _capture_fetch)
    processor = _make_processor(
        _FakeContestDb(),
        vips=["UserA", "UserB"],
        dk=_FakeDraftKingsTrackVipEntries(),
        salary_dir=str(tmp_path),
    )
    with caplog.at_level(logging.INFO):
        contest_id = processor.run("NFL", NFLSport)

    assert contest_id == 123
    assert len(captured["vip_entries"]) == 1
    fetch = _event_messages(caplog, "vip_fetch")
    assert len(fetch) == 1
    assert _parse_event_fields(fetch[0])["requested"] == "1"


def test_process_sport_emits_no_vip_events_when_results_build_fails(monkeypatch, tmp_path, caplog):
    monkeypatch.setattr(
        SportProcessor,
        "_build_results",
        lambda self, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    processor = _make_processor(_FakeContestDb(), vips=["UserA"], salary_dir=str(tmp_path))
    with caplog.at_level(logging.INFO):
        with pytest.raises(StandsParseError):
            processor.run("NFL", NFLSport)

    assert len(_event_messages(caplog, "vip_detection")) == 0
    assert len(_event_messages(caplog, "vip_fetch")) == 0
    assert len(_event_messages(caplog, "vip_sheet_write")) == 0


def test_process_sport_logs_optimizer_skip(tmp_path, caplog):
    processor = _make_processor(_FakeContestDb(), vips=["UserA"], salary_dir=str(tmp_path), nolineups=False)
    with caplog.at_level(logging.INFO):
        processor.run("NFL", NFLSport)

    assert "Skipping optimal lineup for NFL" in caplog.text


def test_process_sport_emits_deterministic_vip_events_on_happy_path(monkeypatch, tmp_path, caplog):
    monkeypatch.setattr(
        "dk_results.sport_processor.fetch_vip_lineups",
        lambda *_a, **_kw: [_FakeVipLineup()],
    )
    processor = _make_processor(_FakeContestDb(), vips=["UserA"], salary_dir=str(tmp_path))
    with caplog.at_level(logging.INFO):
        contest_id = processor.run("NFL", NFLSport)

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


def test_process_sport_no_draft_group_skips_vip_fetch(tmp_path, caplog):
    # draft_group is None, so the processor never calls download_salary_csv to
    # write the file; pre-seed it so standings parsing can still proceed.
    (tmp_path / "DKSalaries_NFL_Saturday.csv").write_text(_salary_csv_text(), encoding="utf-8")
    processor = _make_processor(_FakeContestDbNoDraftGroup(), vips=["UserA"], salary_dir=str(tmp_path))
    with caplog.at_level(logging.INFO):
        contest_id = processor.run("NFL", NFLSport)

    assert contest_id == 123
    fetch = _event_messages(caplog, "vip_fetch")
    sheet_write = _event_messages(caplog, "vip_sheet_write")
    assert len(fetch) == 1
    assert len(sheet_write) == 1

    fetch_fields = _parse_event_fields(fetch[0])
    sheet_fields = _parse_event_fields(sheet_write[0])
    assert fetch_fields["attempted"] == "false"
    assert fetch_fields["reason"] == "no_draft_group"
    assert sheet_fields["written"] == "false"
    assert sheet_fields["reason"] == "no_draft_group"


def test_process_sport_announces_bonuses_when_bonus_sender_configured(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "dk_results.sport_processor.fetch_vip_lineups",
        lambda *_a, **_kw: [_FakeVipLineup()],
    )
    monkeypatch.setattr(
        "dk_results.sport_processor.state.contests_db_path",
        lambda: tmp_path / "contests.db",
    )
    captured: dict = {}

    def _fake_announce(**kwargs):
        captured.update(kwargs)
        return 0

    monkeypatch.setattr("dk_results.sport_processor.announce_vip_bonuses", _fake_announce)

    bonus_sender = object()
    processor = _make_processor(_FakeContestDb(), vips=["UserA"], salary_dir=str(tmp_path), bonus_sender=bonus_sender)
    contest_id = processor.run("NFL", NFLSport)

    assert contest_id == 123
    assert captured["sport"] == "NFL"
    assert captured["contest_id"] == 123
    assert captured["sender"] is bonus_sender
    assert captured["vip_lineups"] == [_FakeVipLineup().to_dict()]


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

    def _fake_snapshot(selected_contests, *, standings_limit: int, generated_at=None):
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


def test_process_sport_uses_structured_log_events(tmp_path, caplog):
    processor = _make_processor(_FakeContestDb(), vips=[], salary_dir=str(tmp_path))
    with caplog.at_level(logging.INFO, logger="dk_results.sport_processor"):
        processor.run("NFL", NFLSport)
    messages = [r.message for r in caplog.records]
    assert any(m.startswith("salary_download") for m in messages)
    assert any(m.startswith("sheet_write_players") for m in messages)
    assert any(m.startswith("min_cash_pts") for m in messages)
    assert not any("Downloading salary file" in m for m in messages)
    assert not any(m == "Writing players to sheet" for m in messages)
    assert not any("Writing min_cash_pts" in m for m in messages)


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


def _selection_messages(caplog):
    return [r.getMessage() for r in caplog.records if r.name == db_main.logger.name]


def test_select_live_contests_logs_one_summary_instead_of_a_warning_per_idle_sport(caplog):
    class _Processor:
        def run(self, sport_name, sport_cls):
            if sport_name == "NFL":
                return 123
            raise NoLiveContestError(sport_name)

    names = ["NBA", "NFL", "NHL"]
    with caplog.at_level(logging.DEBUG):
        selected = db_main.select_live_contests(_Processor(), names, dict.fromkeys(names, object))

    assert selected == {"NFL": 123}
    assert [r for r in caplog.records if r.levelno >= logging.WARNING] == []
    assert _selection_messages(caplog) == [
        "contest_selection selected=NFL no_live=2 requested=3",
        "contest_selection idle=NBA,NHL",
    ]
    assert [r.levelname for r in caplog.records if r.name == db_main.logger.name] == ["INFO", "DEBUG"]


def test_select_live_contests_summary_when_nothing_is_live(caplog):
    class _Processor:
        def run(self, sport_name, sport_cls):
            raise NoLiveContestError(sport_name)

    names = ["NBA", "NFL"]
    with caplog.at_level(logging.INFO):
        assert db_main.select_live_contests(_Processor(), names, dict.fromkeys(names, object)) == {}

    assert _selection_messages(caplog) == ["contest_selection selected=none no_live=2 requested=2"]


def test_select_live_contests_omits_idle_line_when_every_sport_is_live(caplog):
    class _Processor:
        def run(self, sport_name, sport_cls):
            return 1

    with caplog.at_level(logging.DEBUG):
        db_main.select_live_contests(_Processor(), ["NBA"], {"NBA": object})

    assert _selection_messages(caplog) == ["contest_selection selected=NBA no_live=0 requested=1"]


def test_write_train_info_logs_one_debug_line_for_all_clusters(monkeypatch, caplog):
    clusters = {
        1: SimpleNamespace(user_count=5, rank=1, points=101.5, pmr=1.5, lineup=None),
        2: SimpleNamespace(user_count=3, rank=2, points=102.5, pmr=1.5, lineup=None),
        3: SimpleNamespace(user_count=2, rank=3, points=103.5, pmr=1.5, lineup=None),
    }

    class _Finder:
        def __init__(self, _users):
            pass

        def get_total_users(self):
            return 10

        def get_total_users_above_salary(self, _limit):
            return 10

        def get_users_above_salary_spent(self, _limit):
            return dict(clusters)

    monkeypatch.setattr("dk_results.sport_processor.TrainFinder", _Finder)
    sheet = _FakeSheet()
    processor = _make_processor(_FakeContestDb(), vips=[], sheet=sheet)

    with caplog.at_level(logging.DEBUG):
        processor._write_train_info(sheet, SimpleNamespace(users=[object()]))

    debug = [r.getMessage() for r in caplog.records if r.levelno == logging.DEBUG]
    assert debug == ["train_clusters top=5:101.5:1.5,3:102.5:1.5,2:103.5:1.5"]


def test_optimal_lineup_logs_one_debug_line_for_all_player_events(monkeypatch, caplog):
    def _pick(slot, name, event):
        player = SimpleNamespace(name=name, salary=1, fpts=2.0, value=1.5, ownership=3.0, game_info=event)
        return SimpleNamespace(slot=slot, player=player)

    picks = [_pick("QB", "A", "X@Y"), _pick("RB", "B", "Z@W")]

    class _Optimizer:
        def __init__(self, *_args):
            pass

        def get_optimal_lineup(self):
            return list(picks)

    monkeypatch.setattr("dk_results.sport_processor.Optimizer", _Optimizer)
    processor = _make_processor(_FakeContestDb(), vips=[], nolineups=True)

    with caplog.at_level(logging.DEBUG):
        processor._maybe_write_optimal_lineup(
            sheet=_FakeSheet(), results=SimpleNamespace(players={}), sport_cls=NFLSport, sport_name="NFL"
        )

    debug = [r.getMessage() for r in caplog.records if r.levelno == logging.DEBUG]
    assert debug == ["top_player_detail sport=NFL events=A (X@Y); B (Z@W)"]


def test_optimal_lineup_failure_is_logged_once_with_traceback(monkeypatch, caplog):
    class _Optimizer:
        def __init__(self, *_args):
            pass

        def get_optimal_lineup(self):
            raise RuntimeError("solver exploded")

    monkeypatch.setattr("dk_results.sport_processor.Optimizer", _Optimizer)
    processor = _make_processor(_FakeContestDb(), vips=[], nolineups=True)

    with caplog.at_level(logging.ERROR):
        processor._maybe_write_optimal_lineup(
            sheet=_FakeSheet(), results=SimpleNamespace(players={}), sport_cls=NFLSport, sport_name="NFL"
        )

    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(errors) == 1
    assert "NFL" in errors[0].getMessage()
    assert errors[0].exc_info is not None and errors[0].exc_info[0] is RuntimeError


# ── Completed-contest fallback in build_live_snapshot ────────────────────────

_NOW = datetime.datetime(2026, 10, 10, 12, 0, tzinfo=datetime.timezone.utc)


def _completed_db(*, sport: str = "NFL", dk_id: int = 900, completed_at: datetime.datetime = _NOW):
    db = db_main.ContestDatabase(":memory:")
    db.ensure_schema()
    db.conn.execute(
        "INSERT INTO contests (dk_id, sport, name, start_date, draft_group, total_prizes, entries, "
        "entry_fee, entry_count, max_entry_count) VALUES (?, ?, 'Main', '2024-01-01 00:00:00', 1, 1000, 100, "
        "50, 0, 1)",
        (dk_id, sport),
    )
    db.conn.commit()
    db.update_contest(dk_id, positions_paid=10, status="COMPLETED", completed=1, now=completed_at)
    return db


class _LiveFor:
    """A processor whose sports are live (mapped to an id) or idle (absent)."""

    def __init__(self, live: dict[str, int]):
        self._live = live

    def run(self, sport_name, sport_cls):
        if sport_name not in self._live:
            raise NoLiveContestError(sport_name)
        return self._live[sport_name]


def _capture_selection(monkeypatch) -> list[dict[str, int]]:
    calls: list[dict[str, int]] = []

    def _fake(selected_contests, *, standings_limit):
        calls.append(dict(selected_contests))
        return {"sports": {}}

    monkeypatch.setattr(db_main, "build_snapshot_payload", _fake)
    return calls


def test_build_live_snapshot_fills_an_idle_sport_from_a_recently_completed_contest(monkeypatch):
    calls = _capture_selection(monkeypatch)
    db = _completed_db()

    payload = db_main.build_live_snapshot(
        ["NFL"],
        processor=_LiveFor({}),
        contest_db=db,
        now=_NOW + datetime.timedelta(hours=17),
    )

    assert payload is not None
    assert calls == [{"NFL": 900}]


def test_build_live_snapshot_prefers_a_live_contest_over_a_completed_one_in_the_same_sport(monkeypatch):
    calls = _capture_selection(monkeypatch)
    db = _completed_db()

    db_main.build_live_snapshot(["NFL"], processor=_LiveFor({"NFL": 123}), contest_db=db, now=_NOW)

    assert calls == [{"NFL": 123}]


def test_build_live_snapshot_fills_only_the_idle_sports(monkeypatch):
    calls = _capture_selection(monkeypatch)
    db = _completed_db(sport="NFL")

    db_main.build_live_snapshot(["NBA", "NFL"], processor=_LiveFor({"NBA": 5}), contest_db=db, now=_NOW)

    assert calls == [{"NBA": 5, "NFL": 900}]


def test_build_live_snapshot_returns_none_once_the_window_has_closed(monkeypatch):
    calls = _capture_selection(monkeypatch)
    db = _completed_db()

    payload = db_main.build_live_snapshot(
        ["NFL"],
        processor=_LiveFor({}),
        contest_db=db,
        now=_NOW + datetime.timedelta(hours=19),
    )

    assert payload is None
    assert calls == []


def test_build_live_snapshot_does_not_fill_a_sport_whose_live_standings_were_unavailable(monkeypatch):
    calls = _capture_selection(monkeypatch)
    db = _completed_db()

    class _Unavailable:
        def run(self, sport_name, sport_cls):
            raise StandingsUnavailableError(sport_name)

    payload = db_main.build_live_snapshot(["NFL"], processor=_Unavailable(), contest_db=db, now=_NOW)

    assert payload is None
    assert calls == []


def test_build_live_snapshot_fills_an_idle_sport_but_not_one_with_unavailable_standings(monkeypatch):
    calls = _capture_selection(monkeypatch)
    db = _completed_db(sport="NFL", dk_id=900)
    db.conn.execute(
        "INSERT INTO contests (dk_id, sport, name, start_date, draft_group, total_prizes, entries, "
        "entry_fee, entry_count, max_entry_count) VALUES (901, 'NBA', 'Main', '2024-01-01 00:00:00', 1, 1000, "
        "100, 50, 0, 1)"
    )
    db.conn.commit()
    db.update_contest(901, positions_paid=10, status="COMPLETED", completed=1, now=_NOW)

    class _NflUnavailableNbaIdle:
        def run(self, sport_name, sport_cls):
            if sport_name == "NFL":
                raise StandingsUnavailableError(sport_name)
            raise NoLiveContestError(sport_name)

    db_main.build_live_snapshot(["NFL", "NBA"], processor=_NflUnavailableNbaIdle(), contest_db=db, now=_NOW)

    assert calls == [{"NBA": 901}]
