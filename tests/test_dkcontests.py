import datetime

import pytest

import dkcontests
from classes.contest import Contest


def _contest_payload(dk_id: int, *, entries: int = 200, fee: int = 25):
    return {
        "sd": "1700000000000",
        "n": f"Contest {dk_id}",
        "id": dk_id,
        "dg": 10,
        "po": 0,
        "m": entries,
        "a": fee,
        "ec": 0,
        "mec": 1,
        "attr": {"IsDoubleUp": True, "IsGuaranteed": True},
        "gameType": "Classic",
        "gameTypeId": 1,
    }


def test_get_contests_handles_dict_response(monkeypatch):
    monkeypatch.setattr(
        dkcontests,
        "get_lobby_response",
        lambda _sport, live=False: {"Contests": [{"id": 1}]},
    )

    contests = dkcontests.get_contests("NFL", live=False)

    assert contests == [{"id": 1}]


def test_get_contests_handles_list_response(monkeypatch):
    monkeypatch.setattr(dkcontests, "get_lobby_response", lambda _sport, live=False: [{"id": 1}])

    contests = dkcontests.get_contests("NFL", live=True)

    assert contests == [{"id": 1}]


def test_print_stats_includes_largest_entry_count(capsys):
    contests = [
        Contest(_contest_payload(1, entries=150, fee=25), "NFL"),
        Contest(_contest_payload(2, entries=230, fee=25), "NFL"),
    ]

    dkcontests.print_stats(contests)

    out = capsys.readouterr().out
    assert "Breakdown per date:" in out
    assert "$25: 2 contest(s) (largest entry count: 230)" in out


def test_get_largest_contest_applies_query_and_exclude():
    contests = [
        Contest(_contest_payload(1, entries=150, fee=25), "NFL"),
        Contest({**_contest_payload(2, entries=260, fee=25), "n": "Main Slate"}, "NFL"),
        Contest({**_contest_payload(3, entries=280, fee=25), "n": "Main Excluded"}, "NFL"),
    ]

    largest = dkcontests.get_largest_contest(
        contests,
        datetime.datetime(2023, 11, 14),
        entry_fee=25,
        query="Main",
        exclude="Excluded",
    )

    assert largest is not None
    assert largest.id == 2


def test_get_contests_exits_on_invalid_shape(monkeypatch):
    monkeypatch.setattr(dkcontests, "get_lobby_response", lambda _sport, live=False: {"Other": []})

    with pytest.raises(SystemExit):
        dkcontests.get_contests("NFL", live=False)
