"""db_main live-contest selection and train/optimal-lineup logging."""

import logging
from types import SimpleNamespace

import dk_results.cli.db_main as db_main
from dk_results.domain.sport import NFLSport
from dk_results.sport_processor import (
    NoLiveContestError,
)
from tests.db_main_fakes import _FakeContestDb, _FakeSheet, _make_processor


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
