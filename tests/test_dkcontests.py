import datetime
import sys

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


def test_print_sql_insert_uses_typed_values(capsys):
    contest = Contest(
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


def test_print_cron_job_pretty_prints_contest(capsys):
    contest = Contest(_contest_payload(101, entries=22, fee=25), "NFL")

    dkcontests.print_cron_job(contest, "NFL")

    out = capsys.readouterr().out
    assert "'contest': {" in out
    assert "'n': 'Contest 101',\n" in out


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


def test_get_largest_contest_applies_game_type_id():
    contests = [
        Contest({**_contest_payload(11, entries=200), "gameTypeId": 6}, "GOLF"),
        Contest({**_contest_payload(12, entries=300), "gameTypeId": 87}, "GOLF"),
    ]

    largest = dkcontests.get_largest_contest(
        contests,
        datetime.datetime(2023, 11, 14),
        entry_fee=25,
        game_type_id=87,
    )

    assert largest is not None
    assert largest.id == 12


def test_match_contest_criteria_rejects_non_matching_game_type():
    contest = Contest({**_contest_payload(21), "gameTypeId": 6}, "GOLF")
    assert (
        dkcontests.match_contest_criteria(
            contest,
            datetime.datetime(2023, 11, 14),
            entry_fee=25,
            game_type_id=87,
        )
        is False
    )


def test_get_contests_exits_on_invalid_shape(monkeypatch):
    monkeypatch.setattr(dkcontests, "get_lobby_response", lambda _sport, live=False: {"Other": []})

    with pytest.raises(SystemExit):
        dkcontests.get_contests("NFL", live=False)


def test_get_contests_for_sport_class_filters_by_draft_groups(monkeypatch):
    response = {
        "Contests": [
            {**_contest_payload(41), "dg": 41},
            {**_contest_payload(42), "dg": 42},
        ],
        "DraftGroups": [
            {
                "DraftGroupTag": "Featured",
                "ContestStartTimeSuffix": "(Round 4 TOUR)",
                "DraftGroupId": 41,
                "StartDateEst": "2026-02-09T10:45:00.000-05:00",
                "ContestTypeId": 87,
                "GameTypeId": 87,
            },
            {
                "DraftGroupTag": "Featured",
                "ContestStartTimeSuffix": "(Late Round 4 TOUR)",
                "DraftGroupId": 42,
                "StartDateEst": "2026-02-09T12:24:00.000-05:00",
                "ContestTypeId": 154,
                "GameTypeId": 154,
            },
        ],
    }
    monkeypatch.setattr(dkcontests, "get_lobby_response", lambda _sport, live=False: response)

    contests = dkcontests.get_contests_for_sport_class("PGAShowdown")

    assert [contest["id"] for contest in contests] == [41]


def test_main_rejects_live_with_sport_class(monkeypatch):
    monkeypatch.setattr(
        sys,
        "argv",
        ["prog", "--sport-class", "PGAShowdown", "--live"],
    )

    with pytest.raises(SystemExit):
        dkcontests.main()


def test_get_cron_config_shares_pga_values():
    pga = dkcontests.get_cron_config("PGA")
    pga_weekend = dkcontests.get_cron_config("PGAWeekend")
    pga_showdown = dkcontests.get_cron_config("PGAShowdown")

    assert pga == {"sport_length": 8, "get_interval": "4-59/15"}
    assert pga_weekend == pga
    assert pga_showdown == pga


def test_main_passes_sport_class_choices_to_fetcher(monkeypatch):
    captured = {"choices": None}

    class _DummySport:
        contest_restraint_game_type_id = 87

    monkeypatch.setattr(
        dkcontests,
        "get_sport_class_choices",
        lambda: {"PGAShowdown": _DummySport},
    )
    monkeypatch.setattr(
        dkcontests,
        "get_contests_for_sport_class",
        lambda sport_class, choices=None: captured.update({"choices": choices}) or [],
    )
    monkeypatch.setattr(dkcontests, "print_stats", lambda _contests: None)
    monkeypatch.setattr(
        dkcontests,
        "get_largest_contest",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["prog", "--sport-class", "PGAShowdown"],
    )

    with pytest.raises(SystemExit):
        dkcontests.main()

    assert captured["choices"] == {"PGAShowdown": _DummySport}


def test_format_sport_class_game_type_help_lists_constraints():
    help_text = dkcontests.format_sport_class_game_type_help(
        dkcontests.get_sport_class_choices()
    )

    assert "Sport-class gameTypeId constraints:" in help_text
    assert "PGAShowdown: 87" in help_text
    assert "PGAWeekend: 33" in help_text
    assert "NFLShowdown: 96" in help_text
