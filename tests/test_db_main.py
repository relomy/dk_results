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


def test_process_sport_parses_player_stats_only_rows_and_skips_blank_users(
    monkeypatch, tmp_path, live_contest_db, fake_sheet, make_sport_processor
):
    observed = {}

    def _capture_train(self, sheet, results):
        observed["users"] = len(results.users)

    monkeypatch.setattr(SportProcessor, "_write_train_info", _capture_train)
    processor = make_sport_processor(live_contest_db, vips=[], sheet=fake_sheet, salary_dir=str(tmp_path))
    contest_id = processor.run("NFL", NFLSport)

    # Player-only standings row should update ownership/fpts, so Tom Brady appears in player output.
    assert any(row[1] == "Tom Brady" for row in fake_sheet.players)
    # Blank core row should not create phantom users in db_main path.
    assert observed["users"] == 1
    assert contest_id == 123


def test_process_sport_persists_cash_line_and_vip_status(tmp_path, live_contest_db, make_sport_processor):
    db = live_contest_db
    processor = make_sport_processor(db, vips=["UserA"], salary_dir=str(tmp_path))
    contest_id = processor.run("NFL", NFLSport)

    assert contest_id == 123
    assert db.cash_lines[123] == (1, 120.0)
    assert db.vip_statuses[123] == [VipCashStatus(vip_name="UserA", rank=1, points=120.0)]


def test_process_sport_sheet_non_cashing_block_excludes_rows_tied_inside_the_cash_line(
    tmp_path, contest_db_two_paid, dk_tied_at_top, capturing_sheet, make_sport_processor
):
    sheet = capturing_sheet
    processor = make_sport_processor(
        contest_db_two_paid, vips=[], dk=dk_tied_at_top, sheet=sheet, salary_dir=str(tmp_path)
    )
    processor.run("NFL", NFLSport)

    assert sheet.non_cashing_info == [
        ["Non-Cashing Info", ""],
        ["Users not cashing", 1],
        ["Avg PMR Remaining", 30.0],
        ["Top 10 Own% Remaining", ""],
        ["Derrick Henry", 1.0],
    ]


def test_process_sport_persists_none_cash_line_when_positions_paid_missing(
    tmp_path, contest_db_no_positions_paid, make_sport_processor
):
    db = contest_db_no_positions_paid
    processor = make_sport_processor(db, vips=["UserA"], salary_dir=str(tmp_path))
    processor.run("NFL", NFLSport)

    assert db.cash_lines[123] == (None, None)
    # A VIP rank means nothing without a cash line to compare it against, so no
    # rows should be persisted until the cash line itself is known.
    assert db.vip_statuses[123] == []


def test_process_sport_handles_no_live_contest(caplog, contest_db_no_live, make_sport_processor):
    processor = make_sport_processor(contest_db_no_live, vips=["UserA"])
    with caplog.at_level(logging.DEBUG), pytest.raises(NoLiveContestError):
        processor.run("NFL", NFLSport)

    assert len(_event_messages(caplog, "vip_detection")) == 0
    assert len(_event_messages(caplog, "vip_fetch")) == 0
    assert len(_event_messages(caplog, "vip_sheet_write")) == 0
    # Idle sports are the normal case on a 5-minute schedule: the processor stays
    # silent and select_live_contests reports them in one line.
    assert [r for r in caplog.records if r.levelno >= logging.WARNING] == []
    assert not [r for r in caplog.records if "no live contests" in r.getMessage().lower()]


def test_process_sport_emits_no_vip_events_for_standings_skip(
    tmp_path, caplog, live_contest_db, dk_no_standings, make_sport_processor
):
    processor = make_sport_processor(
        live_contest_db,
        vips=["UserA"],
        dk=dk_no_standings,
        salary_dir=str(tmp_path),
    )
    with caplog.at_level(logging.INFO), pytest.raises(StandingsUnavailableError):
        processor.run("NFL", NFLSport)

    assert len(_event_messages(caplog, "vip_detection")) == 0
    assert len(_event_messages(caplog, "vip_fetch")) == 0
    assert len(_event_messages(caplog, "vip_sheet_write")) == 0


def test_process_sport_emits_fetch_error_reason_to_fetch_and_sheet_events(
    monkeypatch, tmp_path, caplog, live_contest_db, make_sport_processor
):
    monkeypatch.setattr(
        "dk_results.sport_processor.fetch_vip_lineups",
        lambda *_a, **_kw: (_ for _ in ()).throw(RuntimeError("fetch failed")),
    )
    processor = make_sport_processor(live_contest_db, vips=["UserA"], salary_dir=str(tmp_path))
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


def test_vip_fetch_requested_uses_filtered_entry_keys(
    monkeypatch, tmp_path, caplog, live_contest_db, dk_track_vip_entries, make_sport_processor
):
    captured: dict = {}

    def _capture_fetch(*_args, vip_entries=None, **_kw):
        captured["vip_entries"] = vip_entries or {}
        return []

    monkeypatch.setattr("dk_results.sport_processor.fetch_vip_lineups", _capture_fetch)
    processor = make_sport_processor(
        live_contest_db,
        vips=["UserA", "UserB"],
        dk=dk_track_vip_entries,
        salary_dir=str(tmp_path),
    )
    with caplog.at_level(logging.INFO):
        contest_id = processor.run("NFL", NFLSport)

    assert contest_id == 123
    assert len(captured["vip_entries"]) == 1
    fetch = _event_messages(caplog, "vip_fetch")
    assert len(fetch) == 1
    assert _parse_event_fields(fetch[0])["requested"] == "1"


def _run_with_failing_results_build(
    monkeypatch, tmp_path, caplog, make_sport_processor, live_contest_db
) -> StandsParseError:
    """Run a VIP-enabled NFL processor whose results build raises, returning the error it surfaces."""
    monkeypatch.setattr(
        SportProcessor,
        "_build_results",
        lambda self, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    processor = make_sport_processor(live_contest_db, vips=["UserA"], salary_dir=str(tmp_path))
    with caplog.at_level(logging.INFO), pytest.raises(StandsParseError) as excinfo:
        processor.run("NFL", NFLSport)
    return excinfo.value


def test_process_sport_emits_no_vip_events_when_results_build_fails(
    monkeypatch, tmp_path, caplog, make_sport_processor, live_contest_db
):
    _run_with_failing_results_build(monkeypatch, tmp_path, caplog, make_sport_processor, live_contest_db)

    assert len(_event_messages(caplog, "vip_detection")) == 0
    assert len(_event_messages(caplog, "vip_fetch")) == 0
    assert len(_event_messages(caplog, "vip_sheet_write")) == 0


def test_process_sport_chains_the_results_build_error_as_the_cause(
    monkeypatch, tmp_path, caplog, make_sport_processor, live_contest_db
):
    error = _run_with_failing_results_build(monkeypatch, tmp_path, caplog, make_sport_processor, live_contest_db)

    assert isinstance(error.__cause__, RuntimeError)
    assert str(error.__cause__) == "boom"


def test_process_sport_logs_optimizer_skip(tmp_path, caplog, live_contest_db, make_sport_processor):
    processor = make_sport_processor(live_contest_db, vips=["UserA"], salary_dir=str(tmp_path), nolineups=False)
    with caplog.at_level(logging.INFO):
        processor.run("NFL", NFLSport)

    assert "Skipping optimal lineup for NFL" in caplog.text


def test_process_sport_emits_deterministic_vip_events_on_happy_path(
    monkeypatch, tmp_path, caplog, live_contest_db, make_sport_processor
):
    monkeypatch.setattr(
        "dk_results.sport_processor.fetch_vip_lineups",
        lambda *_a, **_kw: [_FakeVipLineup()],
    )
    processor = make_sport_processor(live_contest_db, vips=["UserA"], salary_dir=str(tmp_path))
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


def test_process_sport_no_draft_group_skips_vip_fetch(
    tmp_path, caplog, contest_db_no_draft_group, make_sport_processor, salary_csv_text
):
    # draft_group is None, so the processor never calls download_salary_csv to
    # write the file; pre-seed it so standings parsing can still proceed.
    (tmp_path / "DKSalaries_NFL_Saturday.csv").write_text(salary_csv_text, encoding="utf-8")
    processor = make_sport_processor(contest_db_no_draft_group, vips=["UserA"], salary_dir=str(tmp_path))
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


def test_process_sport_announces_bonuses_when_bonus_sender_configured(
    monkeypatch, tmp_path, live_contest_db, make_sport_processor
):
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
    processor = make_sport_processor(
        live_contest_db, vips=["UserA"], salary_dir=str(tmp_path), bonus_sender=bonus_sender
    )
    contest_id = processor.run("NFL", NFLSport)

    assert contest_id == 123
    assert captured["sport"] == "NFL"
    assert captured["contest_id"] == 123
    assert captured["sender"] is bonus_sender
    assert captured["vip_lineups"] == [_FakeVipLineup().to_dict()]


def test_process_sport_uses_structured_log_events(tmp_path, caplog, live_contest_db, make_sport_processor):
    processor = make_sport_processor(live_contest_db, vips=[], salary_dir=str(tmp_path))
    with caplog.at_level(logging.INFO, logger="dk_results.sport_processor"):
        processor.run("NFL", NFLSport)
    messages = [r.message for r in caplog.records]
    assert any(m.startswith("salary_download") for m in messages)
    assert any(m.startswith("sheet_write_players") for m in messages)
    assert any(m.startswith("min_cash_pts") for m in messages)
    assert not any("Downloading salary file" in m for m in messages)
    assert not any(m == "Writing players to sheet" for m in messages)
    assert not any("Writing min_cash_pts" in m for m in messages)
