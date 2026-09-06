import datetime
import sys

import pytest
from pydantic import ValidationError

import dk_results.cli.dkcontests as dkcontests
from dk_results.domain.contest import Contest


def _contest_payload(
    dk_id: int,
    *,
    entries: int = 200,
    fee: int = 25,
    start_dt: datetime.datetime | None = None,
):
    start_dt = start_dt or datetime.datetime.fromtimestamp(1700000000)
    return {
        "sd": str(int(start_dt.timestamp() * 1000)),
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
        Contest.from_lobby(_contest_payload(1, entries=150, fee=25), "NFL"),
        Contest.from_lobby(_contest_payload(2, entries=230, fee=25), "NFL"),
    ]

    dkcontests.print_stats(contests)

    out = capsys.readouterr().out
    assert "Breakdown per date:" in out
    assert "$25:   2 contest(s) (largest entry count:  230)" in out


def test_build_contest_stats_groups_contests_by_start_time():
    contests = [
        Contest.from_lobby(
            _contest_payload(1, entries=150, fee=25, start_dt=datetime.datetime(2023, 11, 14, 19)),
            "NFL",
        ),
        Contest.from_lobby(
            _contest_payload(2, entries=300, fee=25, start_dt=datetime.datetime(2023, 11, 14, 13)),
            "NFL",
        ),
        Contest.from_lobby(
            _contest_payload(3, entries=100, fee=10, start_dt=datetime.datetime(2023, 11, 14, 13)),
            "NFL",
        ),
    ]

    stats = dkcontests.build_contest_stats(contests, include_largest=True)

    assert stats == {
        "2023-11-14": {
            "count": 3,
            "dubs": {
                10: {"count": 1, "largest": 100},
                25: {"count": 2, "largest": 300},
            },
            "by_start_time": {
                "13:00": {
                    "count": 2,
                    "dubs": {
                        10: {"count": 1, "largest": 100},
                        25: {"count": 1, "largest": 300},
                    },
                },
                "19:00": {
                    "count": 1,
                    "dubs": {25: {"count": 1, "largest": 150}},
                },
            },
        }
    }


def test_build_contest_stats_counts_double_ups_without_largest_entries():
    contests = [
        Contest.from_lobby(_contest_payload(1, fee=10, start_dt=datetime.datetime(2023, 11, 14, 13)), "NFL"),
        Contest.from_lobby(_contest_payload(2, fee=10, start_dt=datetime.datetime(2023, 11, 14, 13)), "NFL"),
        Contest.from_lobby(_contest_payload(3, fee=25, start_dt=datetime.datetime(2023, 11, 14, 19)), "NFL"),
    ]

    stats = dkcontests.build_contest_stats(contests)

    assert stats["2023-11-14"]["dubs"] == {10: 2, 25: 1}
    assert stats["2023-11-14"]["by_start_time"]["13:00"]["dubs"] == {10: 2}
    assert stats["2023-11-14"]["by_start_time"]["19:00"]["dubs"] == {25: 1}


def test_build_contest_stats_combines_contests_in_the_same_displayed_minute():
    contests = [
        Contest.from_lobby(_contest_payload(1, start_dt=datetime.datetime(2023, 11, 14, 19, 0)), "NFL"),
        Contest.from_lobby(_contest_payload(2, start_dt=datetime.datetime(2023, 11, 14, 19, 0, 45)), "NFL"),
    ]

    stats = dkcontests.build_contest_stats(contests)

    assert stats["2023-11-14"]["by_start_time"] == {"19:00": {"count": 2, "dubs": {25: 2}}}


def test_print_stats_breaks_dates_down_by_sorted_start_time(capsys):
    contests = [
        Contest.from_lobby(
            _contest_payload(1, entries=150, fee=25, start_dt=datetime.datetime(2023, 11, 14, 19)),
            "NFL",
        ),
        Contest.from_lobby(
            _contest_payload(2, entries=300, fee=25, start_dt=datetime.datetime(2023, 11, 14, 13)),
            "NFL",
        ),
        Contest.from_lobby(
            _contest_payload(3, entries=100, fee=10, start_dt=datetime.datetime(2023, 11, 14, 13)),
            "NFL",
        ),
    ]

    dkcontests.print_stats(contests)

    assert capsys.readouterr().out.splitlines() == [
        "Breakdown per date:",
        "2023-11-14 -   3 total contests",
        "  13:00 -   2 total contests",
        "    Single-entry double ups:",
        "           $10:   1 contest(s) (largest entry count:  100)",
        "           $25:   1 contest(s) (largest entry count:  300)",
        "  19:00 -   1 total contests",
        "    Single-entry double ups:",
        "           $25:   1 contest(s) (largest entry count:  150)",
    ]


def test_print_stats_sorts_dates_chronologically(capsys):
    contests = [
        Contest.from_lobby(_contest_payload(1, start_dt=datetime.datetime(2023, 11, 15, 19)), "NFL"),
        Contest.from_lobby(_contest_payload(2, start_dt=datetime.datetime(2023, 11, 14, 13)), "NFL"),
    ]

    dkcontests.print_stats(contests)

    lines = capsys.readouterr().out.splitlines()
    assert lines.index("2023-11-14 -   1 total contests") < lines.index("2023-11-15 -   1 total contests")


def test_print_stats_filters_to_requested_start_date(capsys):
    contests = [
        Contest.from_lobby(_contest_payload(1, start_dt=datetime.datetime(2023, 11, 14, 13)), "NFL"),
        Contest.from_lobby(_contest_payload(2, start_dt=datetime.datetime(2023, 11, 15, 13)), "NFL"),
    ]

    dkcontests.print_stats(contests, start_date=datetime.date(2023, 11, 14))

    out = capsys.readouterr().out
    assert "2023-11-14 -   1 total contests" in out
    assert "2023-11-15" not in out


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


def test_from_lobby_maps_readable_fields_and_flags():
    contest = Contest.from_lobby(
        {**_contest_payload(7, entries=200, fee=25), "n": "  Padded Name  "},
        "NFL",
    )

    assert contest.id == 7
    assert contest.name == "Padded Name"
    assert contest.draft_group == 10
    assert contest.entry_fee == 25
    assert contest.entry_count == 0
    assert contest.max_entry_count == 1
    assert contest.game_type == "Classic"
    assert contest.game_type_id == 1
    assert contest.start_dt == datetime.datetime.fromtimestamp(1700000000)
    assert contest.is_double_up is True
    assert contest.is_guaranteed is True


def test_from_lobby_accepts_fractional_total_prizes():
    contest = Contest.from_lobby({**_contest_payload(13), "po": 22.5}, "NFL")

    assert contest.total_prizes == 22.5


def test_from_lobby_flags_default_false_when_attr_key_absent():
    contest = Contest.from_lobby({**_contest_payload(8), "attr": {}}, "NFL")

    assert contest.is_double_up is False
    assert contest.is_guaranteed is False
    assert contest.is_starred is False


def test_from_lobby_missing_required_key_raises_naming_field():
    payload = _contest_payload(9)
    del payload["sd"]

    with pytest.raises(ValidationError) as excinfo:
        Contest.from_lobby(payload, "NFL")

    message = str(excinfo.value)
    assert "sd" in message
    assert "Field required" in message


def test_contest_is_frozen():
    contest = Contest.from_lobby(_contest_payload(10), "NFL")

    with pytest.raises(ValidationError):
        contest.name = "mutated"


def test_get_largest_contest_applies_query_and_exclude():
    contests = [
        Contest.from_lobby(_contest_payload(1, entries=150, fee=25), "NFL"),
        Contest.from_lobby({**_contest_payload(2, entries=260, fee=25), "n": "Main Slate"}, "NFL"),
        Contest.from_lobby({**_contest_payload(3, entries=280, fee=25), "n": "Main Excluded"}, "NFL"),
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
        Contest.from_lobby({**_contest_payload(11, entries=200), "gameTypeId": 6}, "GOLF"),
        Contest.from_lobby({**_contest_payload(12, entries=300), "gameTypeId": 87}, "GOLF"),
    ]

    largest = dkcontests.get_largest_contest(
        contests,
        datetime.datetime(2023, 11, 14),
        entry_fee=25,
        game_type_id=87,
    )

    assert largest is not None
    assert largest.id == 12


def test_get_largest_contest_reports_candidates_eliminated_by_query(capsys):
    contests = [
        Contest.from_lobby({**_contest_payload(1, entries=150, fee=25), "n": "Afternoon Slate"}, "NFL"),
    ]

    largest = dkcontests.get_largest_contest(
        contests,
        datetime.datetime(2023, 11, 14),
        entry_fee=25,
        query="Night",
    )

    assert largest is None
    out = capsys.readouterr().out
    assert "matched none of the $25 double-up(s)" in out
    assert "Afternoon Slate" in out


def test_get_available_dub_fees_returns_descending_distinct_fees():
    date = datetime.datetime(2023, 11, 14)
    timestamp = "1700000000000"
    contests = [
        Contest.from_lobby(_contest_payload(1, fee=25), "NFL"),
        Contest.from_lobby(_contest_payload(2, fee=10), "NFL"),
        Contest.from_lobby(_contest_payload(3, fee=10), "NFL"),
        Contest.from_lobby({**_contest_payload(4, fee=5), "attr": {"IsDoubleUp": False, "IsGuaranteed": True}}, "NFL"),
    ]
    assert all(c.start_dt.date() == date.date() for c in contests), "fixture timestamp drifted"
    del timestamp

    assert dkcontests.get_available_dub_fees(contests, date) == [25, 10]


def test_get_available_dub_fees_restricts_to_game_type_id():
    date = datetime.datetime(2023, 11, 14)
    contests = [
        Contest.from_lobby({**_contest_payload(1, fee=25), "gameTypeId": 87}, "NFL"),
        Contest.from_lobby({**_contest_payload(2, fee=10), "gameTypeId": 6}, "NFL"),
    ]

    assert dkcontests.get_available_dub_fees(contests, date, game_type_id=87) == [25]


def test_get_largest_contest_with_fallback_skips_tiers_outside_game_type_id(capsys):
    contests = [
        Contest.from_lobby({**_contest_payload(1, entries=150, fee=25), "gameTypeId": 87}, "GOLF"),
        Contest.from_lobby({**_contest_payload(2, entries=300, fee=10), "gameTypeId": 6}, "GOLF"),
    ]

    largest = dkcontests.get_largest_contest_with_fallback(
        contests,
        datetime.datetime(2023, 11, 14),
        entry_fee=25,
        query="Night",
        game_type_id=87,
    )

    assert largest is None
    out = capsys.readouterr().out
    assert "[$10]" not in out


def test_get_largest_contest_with_fallback_drops_to_lower_tier(capsys):
    contests = [
        Contest.from_lobby({**_contest_payload(1, entries=150, fee=25), "n": "Afternoon Slate"}, "NFL"),
        Contest.from_lobby({**_contest_payload(2, entries=300, fee=10), "n": "Thursday Night Slate"}, "NFL"),
    ]

    largest = dkcontests.get_largest_contest_with_fallback(
        contests,
        datetime.datetime(2023, 11, 14),
        entry_fee=25,
        query="Night",
    )

    assert largest is not None
    assert largest.id == 2
    assert "falling back to $10" in capsys.readouterr().out


def test_get_largest_contest_with_fallback_labels_each_tiers_diagnostics(capsys):
    contests = [
        Contest.from_lobby({**_contest_payload(1, entries=150, fee=25), "n": "Afternoon Slate"}, "NFL"),
        Contest.from_lobby({**_contest_payload(2, entries=300, fee=10), "n": "Thursday Night Slate"}, "NFL"),
    ]

    dkcontests.get_largest_contest_with_fallback(
        contests,
        datetime.datetime(2023, 11, 14),
        entry_fee=25,
        query="Night",
    )

    out = capsys.readouterr().out
    assert "[$25] contests size:" in out
    assert "[$25] number of contests meeting requirements:" in out
    assert "[$10] contests size:" in out
    assert "[$10] number of contests meeting requirements:" in out


def test_get_largest_contest_with_fallback_no_label_for_single_tier(capsys):
    contests = [
        Contest.from_lobby({**_contest_payload(1, entries=150, fee=25), "n": "Afternoon Slate"}, "NFL"),
    ]

    dkcontests.get_largest_contest_with_fallback(
        contests,
        datetime.datetime(2023, 11, 14),
        entry_fee=25,
    )

    out = capsys.readouterr().out
    assert "contests size: 1" in out
    assert "[$25]" not in out


def test_get_largest_contest_with_fallback_returns_none_when_no_tier_matches():
    contests = [
        Contest.from_lobby({**_contest_payload(1, entries=150, fee=25), "n": "Afternoon Slate"}, "NFL"),
    ]

    largest = dkcontests.get_largest_contest_with_fallback(
        contests,
        datetime.datetime(2023, 11, 14),
        entry_fee=25,
        query="Night",
    )

    assert largest is None


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


def test_get_contests_for_sport_class_uses_anonymous_lobby_path(anonymous_lobby):
    """Sport-class mode resolves draft groups without touching auth machinery (ADR-0009)."""
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
        ],
    }
    anonymous_lobby(response)

    contests = dkcontests.get_contests_for_sport_class("PGAShowdown")

    assert [contest["id"] for contest in contests] == [41]


def test_get_draft_group_info_returns_matching_entry():
    response = {
        "DraftGroups": [
            {"DraftGroupId": 100, "ContestTypeId": 87},
            {"DraftGroupId": 200, "ContestTypeId": 33},
        ]
    }

    assert dkcontests.get_draft_group_info(response, 200) == {
        "DraftGroupId": 200,
        "ContestTypeId": 33,
    }
    assert dkcontests.get_draft_group_info(response, 999) is None
    assert dkcontests.get_draft_group_info([], 200) is None


def test_main_bootstraps_runtime_before_parsing_arguments(monkeypatch):
    calls = []
    monkeypatch.setattr(dkcontests, "load_and_apply_settings", lambda: calls.append("bootstrap"))
    monkeypatch.setattr(sys, "argv", ["dkcontests", "--help"])

    with pytest.raises(SystemExit):
        dkcontests.main()

    assert calls == ["bootstrap"]


def test_main_rejects_live_with_sport_class(monkeypatch):
    monkeypatch.setattr(
        sys,
        "argv",
        ["prog", "--sport-class", "PGAShowdown", "--live"],
    )

    with pytest.raises(SystemExit):
        dkcontests.main()


def test_main_passes_sport_class_choices_to_response_filters(monkeypatch):
    captured = {"sport": None, "sport_obj": None}

    class _DummySport:
        name = "PGAShowdown"
        contest_restraint_game_type_id = 87

        @staticmethod
        def get_primary_sport():
            return "GOLF"

    monkeypatch.setattr(
        dkcontests,
        "get_sport_class_choices",
        lambda: {"PGAShowdown": _DummySport},
    )
    monkeypatch.setattr(
        dkcontests,
        "get_lobby_response",
        lambda sport, live=False: captured.update({"sport": sport}) or {"Contests": [], "DraftGroups": []},
    )
    monkeypatch.setattr(
        dkcontests,
        "filter_draft_groups",
        lambda _groups, sport_obj: captured.update({"sport_obj": sport_obj}) or [],
    )
    monkeypatch.setattr(dkcontests, "print_stats", lambda _contests, **_kwargs: None)
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

    assert captured["sport"] == "GOLF"
    assert captured["sport_obj"] is _DummySport


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

        def create_table(self):
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

        def create_table(self):
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


def test_format_sport_class_game_type_help_lists_constraints():
    help_text = dkcontests.format_sport_class_game_type_help(dkcontests.get_sport_class_choices())

    assert "Sport-class gameTypeId constraints:" in help_text
    assert "PGAShowdown: 87" in help_text
    assert "PGAWeekend: 33" in help_text
    assert "NFLShowdown: 96" in help_text


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

        def create_table(self):
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
