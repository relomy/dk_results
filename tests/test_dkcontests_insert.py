"""dkcontests contest insert: SQL preview, confirmation and contests.db writes."""

import sys

import pytest

import dk_results.cli.dkcontests as dkcontests
from dk_results.domain.contest import Contest
from tests.dkcontests_payloads import _contest_payload


def test_print_sql_insert_uses_typed_values(capsys):
    contest = Contest.from_lobby(
        {**_contest_payload(99, entries=22, fee=25), "n": "Weekend PGA TOUR Single Entry"},
        "GOLF",
    )

    dkcontests.print_sql_insert(contest)

    out = capsys.readouterr().out
    assert "INSERT INTO contests (" in out
    assert "positions_paid" in out
    assert "'GOLF'" in out
    assert "99" in out
    assert "'99'" not in out
    assert "NULL" in out


def test_confirm_insert_accepts_y(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _prompt: "y")
    assert dkcontests.confirm_insert() is True


def test_confirm_insert_accepts_yes_case_insensitive(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _prompt: "YES")
    assert dkcontests.confirm_insert() is True


def test_confirm_insert_defaults_to_no_on_empty_input(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _prompt: "")
    assert dkcontests.confirm_insert() is False


def test_confirm_insert_rejects_arbitrary_text(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _prompt: "nah")
    assert dkcontests.confirm_insert() is False


def test_maybe_insert_contest_skips_db_when_flag_not_set(monkeypatch):
    contest = Contest.from_lobby(_contest_payload(1), "NFL")

    def _boom(*_args, **_kwargs):
        raise AssertionError("ContestDatabase should not be constructed")

    monkeypatch.setattr(dkcontests, "ContestDatabase", _boom)

    dkcontests.maybe_insert_contest(contest, insert=False)


def test_maybe_insert_contest_skips_db_when_declined(monkeypatch):
    contest = Contest.from_lobby(_contest_payload(1), "NFL")

    def _boom(*_args, **_kwargs):
        raise AssertionError("ContestDatabase should not be constructed")

    monkeypatch.setattr(dkcontests, "ContestDatabase", _boom)
    monkeypatch.setattr(dkcontests, "confirm_insert", lambda: False)

    dkcontests.maybe_insert_contest(contest, insert=True)


def test_maybe_insert_contest_inserts_when_confirmed(monkeypatch, capsys):
    contest = Contest.from_lobby(_contest_payload(1), "NFL")
    calls = {"inserted": None, "closed": False, "db_path": None, "created_table": False}

    class FakeDB:
        def __init__(self, db_path):
            calls["db_path"] = db_path

        def ensure_schema(self):
            calls["created_table"] = True

        def compare_contests(self, contests):
            return [c.id for c in contests]

        def insert_contests(self, contests):
            calls["inserted"] = list(contests)

        def close(self):
            calls["closed"] = True

    monkeypatch.setattr(dkcontests, "ContestDatabase", FakeDB)
    monkeypatch.setattr(dkcontests, "confirm_insert", lambda: True)
    monkeypatch.setattr(dkcontests.state, "contests_db_path", lambda: "/tmp/contests.db")

    dkcontests.maybe_insert_contest(contest, insert=True)

    assert calls["inserted"] == [contest]
    assert calls["closed"] is True
    assert calls["db_path"] == "/tmp/contests.db"
    assert calls["created_table"] is True
    assert "Inserted contest 1" in capsys.readouterr().out


def test_maybe_insert_contest_reports_existing_duplicate(monkeypatch, capsys):
    contest = Contest.from_lobby(_contest_payload(1), "NFL")

    class FakeDB:
        def __init__(self, _db_path):
            pass

        def ensure_schema(self):
            pass

        def compare_contests(self, _contests):
            return []

        def insert_contests(self, _contests):
            pass

        def close(self):
            pass

    monkeypatch.setattr(dkcontests, "ContestDatabase", FakeDB)
    monkeypatch.setattr(dkcontests, "confirm_insert", lambda: True)
    monkeypatch.setattr(dkcontests.state, "contests_db_path", lambda: "/tmp/contests.db")

    dkcontests.maybe_insert_contest(contest, insert=True)

    assert "already exists in contests.db" in capsys.readouterr().out


def test_main_without_insert_flag_never_touches_db(monkeypatch, capsys):
    contest_payload = _contest_payload(1, entries=200, fee=25)
    monkeypatch.setattr(dkcontests, "get_lobby_response", lambda _sport, live=False: {"Contests": [contest_payload]})

    def _boom(*_args, **_kwargs):
        raise AssertionError("ContestDatabase should not be constructed")

    monkeypatch.setattr(dkcontests, "ContestDatabase", _boom)
    monkeypatch.setattr(sys, "argv", ["prog", "-s", "NFL", "-e", "25", "-d", "2023-11-14"])

    dkcontests.main()

    assert "INSERT INTO contests (" in capsys.readouterr().out


def test_main_with_insert_flag_prompts_and_inserts_confirmed_contest(monkeypatch, capsys):
    contest_payload = _contest_payload(1, entries=200, fee=25)
    monkeypatch.setattr(dkcontests, "get_lobby_response", lambda _sport, live=False: {"Contests": [contest_payload]})

    calls = {"inserted": None}

    class FakeDB:
        def __init__(self, _db_path):
            pass

        def ensure_schema(self):
            pass

        def compare_contests(self, contests):
            return [c.id for c in contests]

        def insert_contests(self, contests):
            calls["inserted"] = list(contests)

        def close(self):
            pass

    monkeypatch.setattr(dkcontests, "ContestDatabase", FakeDB)
    monkeypatch.setattr(dkcontests, "confirm_insert", lambda: True)
    monkeypatch.setattr(dkcontests.state, "contests_db_path", lambda: "/tmp/contests.db")
    monkeypatch.setattr(sys, "argv", ["prog", "-s", "NFL", "-e", "25", "-d", "2023-11-14", "--insert"])

    dkcontests.main()

    assert calls["inserted"] is not None
    assert calls["inserted"][0].id == 1
    assert "INSERT INTO contests (" in capsys.readouterr().out


def test_main_with_insert_flag_declined_does_not_insert(monkeypatch):
    contest_payload = _contest_payload(1, entries=200, fee=25)
    monkeypatch.setattr(dkcontests, "get_lobby_response", lambda _sport, live=False: {"Contests": [contest_payload]})

    def _boom(*_args, **_kwargs):
        raise AssertionError("ContestDatabase should not be constructed")

    monkeypatch.setattr(dkcontests, "ContestDatabase", _boom)
    monkeypatch.setattr(dkcontests, "confirm_insert", lambda: False)
    monkeypatch.setattr(sys, "argv", ["prog", "-s", "NFL", "-e", "25", "-d", "2023-11-14", "--insert"])

    dkcontests.main()


def test_main_with_insert_flag_and_no_match_exits_before_prompt(monkeypatch):
    monkeypatch.setattr(dkcontests, "get_lobby_response", lambda _sport, live=False: {"Contests": []})

    def _boom():
        raise AssertionError("confirm_insert should not be called with no match")

    monkeypatch.setattr(dkcontests, "confirm_insert", _boom)
    monkeypatch.setattr(sys, "argv", ["prog", "-s", "NFL", "-e", "25", "--insert"])

    with pytest.raises(SystemExit):
        dkcontests.main()
