"""build_live_snapshot: filling idle sports from recently completed contests."""

import datetime

import dk_results.cli.db_main as db_main
from dk_results.domain.sport import Sport
from dk_results.sport_processor import (
    NoLiveContestError,
    SportProcessor,
    StandingsUnavailableError,
)

_NOW = datetime.datetime(2026, 10, 10, 12, 0, tzinfo=datetime.UTC)


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


def _live_for(make_scripted_processor, live: dict[str, int]) -> SportProcessor:
    """A processor whose sports are live (mapped to an id) or idle (absent)."""

    def _run(sport_name: str, sport_cls: type[Sport]) -> int:
        if sport_name not in live:
            raise NoLiveContestError(sport_name)
        return live[sport_name]

    return make_scripted_processor(_run)


def _capture_selection(monkeypatch) -> list[dict[str, int]]:
    calls: list[dict[str, int]] = []

    def _fake(selected_contests, *, standings_limit, producer_commit=None):
        calls.append(dict(selected_contests))
        return {"sports": {}}

    monkeypatch.setattr(db_main, "build_snapshot_payload", _fake)
    return calls


def test_build_live_snapshot_fills_an_idle_sport_from_a_recently_completed_contest(
    monkeypatch, make_scripted_processor
):
    calls = _capture_selection(monkeypatch)
    db = _completed_db()

    payload = db_main.build_live_snapshot(
        ["NFL"],
        processor=_live_for(make_scripted_processor, {}),
        contest_db=db,
        now=_NOW + datetime.timedelta(hours=17),
    )

    assert payload is not None
    assert calls == [{"NFL": 900}]


def test_build_live_snapshot_prefers_a_live_contest_over_a_completed_one_in_the_same_sport(
    monkeypatch, make_scripted_processor
):
    calls = _capture_selection(monkeypatch)
    db = _completed_db()

    db_main.build_live_snapshot(
        ["NFL"], processor=_live_for(make_scripted_processor, {"NFL": 123}), contest_db=db, now=_NOW
    )

    assert calls == [{"NFL": 123}]


def test_build_live_snapshot_fills_only_the_idle_sports(monkeypatch, make_scripted_processor):
    calls = _capture_selection(monkeypatch)
    db = _completed_db(sport="NFL")

    db_main.build_live_snapshot(
        ["NBA", "NFL"], processor=_live_for(make_scripted_processor, {"NBA": 5}), contest_db=db, now=_NOW
    )

    assert calls == [{"NBA": 5, "NFL": 900}]


def test_build_live_snapshot_returns_none_once_the_window_has_closed(monkeypatch, make_scripted_processor):
    calls = _capture_selection(monkeypatch)
    db = _completed_db()

    payload = db_main.build_live_snapshot(
        ["NFL"],
        processor=_live_for(make_scripted_processor, {}),
        contest_db=db,
        now=_NOW + datetime.timedelta(hours=19),
    )

    assert payload is None
    assert calls == []


def test_build_live_snapshot_does_not_fill_a_sport_whose_live_standings_were_unavailable(
    monkeypatch, make_scripted_processor
):
    calls = _capture_selection(monkeypatch)
    db = _completed_db()

    def _unavailable(sport_name: str, sport_cls: type[Sport]) -> int:
        raise StandingsUnavailableError(sport_name)

    payload = db_main.build_live_snapshot(
        ["NFL"], processor=make_scripted_processor(_unavailable), contest_db=db, now=_NOW
    )

    assert payload is None
    assert calls == []


def test_build_live_snapshot_fills_an_idle_sport_but_not_one_with_unavailable_standings(
    monkeypatch, make_scripted_processor
):
    calls = _capture_selection(monkeypatch)
    db = _completed_db(sport="NFL", dk_id=900)
    db.conn.execute(
        "INSERT INTO contests (dk_id, sport, name, start_date, draft_group, total_prizes, entries, "
        "entry_fee, entry_count, max_entry_count) VALUES (901, 'NBA', 'Main', '2024-01-01 00:00:00', 1, 1000, "
        "100, 50, 0, 1)"
    )
    db.conn.commit()
    db.update_contest(901, positions_paid=10, status="COMPLETED", completed=1, now=_NOW)

    def _nfl_unavailable_nba_idle(sport_name: str, sport_cls: type[Sport]) -> int:
        if sport_name == "NFL":
            raise StandingsUnavailableError(sport_name)
        raise NoLiveContestError(sport_name)

    db_main.build_live_snapshot(
        ["NFL", "NBA"], processor=make_scripted_processor(_nfl_unavailable_nba_idle), contest_db=db, now=_NOW
    )

    assert calls == [{"NBA": 901}]
