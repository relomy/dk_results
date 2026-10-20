"""dkcontests CLI entry point (lobby fetch, draft group lookup, arguments) and Contest.from_lobby."""

import datetime
import sys

import pytest
from pydantic import ValidationError

import dk_results.cli.dkcontests as dkcontests
from dk_results.domain.contest import Contest
from dk_results.lobby.fetch import SportClassContests
from tests.dkcontests_payloads import _contest_payload


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


def test_get_contests_exits_on_invalid_shape(monkeypatch):
    monkeypatch.setattr(dkcontests, "get_lobby_response", lambda _sport, live=False: {"Other": []})

    with pytest.raises(SystemExit):
        dkcontests.get_contests("NFL", live=False)


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
    captured = {"sport_cls": None}

    class _DummySport:
        name = "PGAShowdown"
        contest_restraint_game_type_id = 87

        @staticmethod
        def get_primary_sport():
            return "GOLF"

    def fake_load_sport_class_contests(sport_cls):
        captured["sport_cls"] = sport_cls
        return SportClassContests([], set())

    monkeypatch.setattr(
        dkcontests,
        "get_sport_class_choices",
        lambda: {"PGAShowdown": _DummySport},
    )
    monkeypatch.setattr(
        dkcontests,
        "load_sport_class_contests",
        fake_load_sport_class_contests,
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

    assert captured["sport_cls"] is _DummySport


def test_format_sport_class_game_type_help_lists_constraints():
    help_text = dkcontests.format_sport_class_game_type_help(dkcontests.get_sport_class_choices())

    assert "Sport-class gameTypeId constraints:" in help_text
    assert "PGAShowdown: 87" in help_text
    assert "PGAWeekend: 33" in help_text
    assert "NFLShowdown: 96" in help_text


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
