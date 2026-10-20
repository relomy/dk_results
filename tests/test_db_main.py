"""SportProcessor.run: standings parsing, cash line, VIP and sheet events, bonus announcements."""

import logging

import pytest

from dk_results.domain.sport import NFLSport
from dk_results.persistence.contestdatabase import VipCashStatus
from dk_results.sport_processor import (
    NoLiveContestError,
    SportProcessor,
    StandingsUnavailableError,
    StandsParseError,
)
from tests.db_main_fakes import _FakeContestDb, _FakeDraftKings, _FakeSheet, _make_processor, _salary_csv_text


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
