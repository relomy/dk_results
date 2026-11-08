"""db_main live-contest selection and train/optimal-lineup logging."""

import logging
from types import SimpleNamespace

import dk_results.cli.db_main as db_main
from dk_results.domain.sport import NFLSport, Sport
from dk_results.domain.user import User
from dk_results.sport_processor import (
    NoLiveContestError,
)


def _assert_traceback_is(record: logging.LogRecord, exc_type: type[BaseException]) -> None:
    assert isinstance(record.exc_info, tuple), "expected the error record to carry a traceback"
    assert record.exc_info[0] is exc_type


def _selection_messages(caplog):
    return [r.getMessage() for r in caplog.records if r.name == db_main.logger.name]


def test_select_live_contests_logs_one_summary_instead_of_a_warning_per_idle_sport(caplog, make_scripted_processor):
    def _run(sport_name: str, sport_cls: type[Sport]) -> int:
        if sport_name == "NFL":
            return 123
        raise NoLiveContestError(sport_name)

    names = ["NBA", "NFL", "NHL"]
    with caplog.at_level(logging.DEBUG):
        selected = db_main.select_live_contests(make_scripted_processor(_run), names, dict.fromkeys(names, NFLSport))

    assert selected == {"NFL": 123}
    assert [r for r in caplog.records if r.levelno >= logging.WARNING] == []
    assert _selection_messages(caplog) == [
        "contest_selection selected=NFL no_live=2 requested=3",
        "contest_selection idle=NBA,NHL",
    ]
    assert [r.levelname for r in caplog.records if r.name == db_main.logger.name] == ["INFO", "DEBUG"]


def test_select_live_contests_summary_when_nothing_is_live(caplog, make_scripted_processor):
    def _run(sport_name: str, sport_cls: type[Sport]) -> int:
        raise NoLiveContestError(sport_name)

    names = ["NBA", "NFL"]
    with caplog.at_level(logging.INFO):
        assert db_main.select_live_contests(make_scripted_processor(_run), names, dict.fromkeys(names, NFLSport)) == {}

    assert _selection_messages(caplog) == ["contest_selection selected=none no_live=2 requested=2"]


def test_select_live_contests_omits_idle_line_when_every_sport_is_live(caplog, make_scripted_processor):
    def _run(sport_name: str, sport_cls: type[Sport]) -> int:
        return 1

    with caplog.at_level(logging.DEBUG):
        db_main.select_live_contests(make_scripted_processor(_run), ["NBA"], {"NBA": NFLSport})

    assert _selection_messages(caplog) == ["contest_selection selected=NBA no_live=0 requested=1"]


def test_write_train_info_logs_one_debug_line_for_all_clusters(
    monkeypatch, caplog, live_contest_db, fake_sheet, make_sport_processor, make_standings
):
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
    sheet = fake_sheet
    processor = make_sport_processor(live_contest_db, vips=[], sheet=sheet)

    with caplog.at_level(logging.DEBUG):
        processor._write_train_info(sheet, make_standings(users=[User(1, "e1", "one", "20", 100.0, "")]))

    debug = [r.getMessage() for r in caplog.records if r.levelno == logging.DEBUG]
    assert debug == ["train_clusters top=5:101.5:1.5,3:102.5:1.5,2:103.5:1.5"]


def test_optimal_lineup_logs_one_debug_line_for_all_player_events(
    monkeypatch, caplog, live_contest_db, fake_sheet, make_sport_processor, make_standings
):
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
    processor = make_sport_processor(live_contest_db, vips=[], nolineups=True)

    with caplog.at_level(logging.DEBUG):
        processor._maybe_write_optimal_lineup(
            sheet=fake_sheet, results=make_standings(), sport_cls=NFLSport, sport_name="NFL"
        )

    debug = [r.getMessage() for r in caplog.records if r.levelno == logging.DEBUG]
    assert debug == ["top_player_detail sport=NFL events=A (X@Y); B (Z@W)"]


def test_optimal_lineup_failure_is_logged_once_with_traceback(
    monkeypatch, caplog, live_contest_db, fake_sheet, make_sport_processor, make_standings
):
    class _Optimizer:
        def __init__(self, *_args):
            pass

        def get_optimal_lineup(self):
            raise RuntimeError("solver exploded")

    monkeypatch.setattr("dk_results.sport_processor.Optimizer", _Optimizer)
    processor = make_sport_processor(live_contest_db, vips=[], nolineups=True)

    with caplog.at_level(logging.ERROR):
        processor._maybe_write_optimal_lineup(
            sheet=fake_sheet, results=make_standings(), sport_cls=NFLSport, sport_name="NFL"
        )

    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(errors) == 1
    assert "NFL" in errors[0].getMessage()
    _assert_traceback_is(errors[0], RuntimeError)
