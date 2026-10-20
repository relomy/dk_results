"""Lobby feed parsing, date helpers and fetch used by the double-up finder."""

import argparse
import datetime

import pytest

from dk_results.domain.sport import Sport
from dk_results.lobby.common import get_salary_date, is_time_between, valid_date
from dk_results.lobby.fetch import get_dk_lobby
from dk_results.lobby.parsing import (
    build_draft_group_start_map,
    get_contests_from_response,
    log_draft_group_event,
)


def test_build_draft_group_start_map_filters_and_parses():
    draft_groups = [
        {"DraftGroupId": 10, "StartDateEst": "2024-02-01T12:30:00.000-05:00"},
        {"DraftGroupId": 20, "StartDateEst": "2024-02-02T13:00:00.000-05:00"},
        {"DraftGroupId": 30, "StartDateEst": None},
        {"DraftGroupId": 40, "StartDateEst": "invalid"},
    ]
    allowed_ids = {10, 30, 40}

    result = build_draft_group_start_map(draft_groups, allowed_ids)

    assert result == {10: datetime.datetime(2024, 2, 1, 12, 30, 0)}


def test_get_contests_from_response_list_and_dict():
    assert get_contests_from_response([{1: 2}]) == [{1: 2}]
    assert get_contests_from_response({"Contests": [1]}) == [1]


def test_get_contests_from_response_invalid():
    with pytest.raises(SystemExit):
        get_contests_from_response({"Other": []})


def test_log_draft_group_event_includes_reason(monkeypatch):
    captured = []

    def fake_log(level, msg, *args):
        captured.append(msg % args)

    monkeypatch.setattr("dk_results.lobby.parsing.logger.log", fake_log)

    class DummySport(Sport):
        name = "TEST"

    log_draft_group_event(
        "Skip",
        DummySport,
        datetime.datetime(2024, 1, 1, 0, 0, 0),
        10,
        "Featured",
        "(Main)",
        1,
        2,
        reason="suffix mismatch",
    )

    assert any("reason" in msg for msg in captured)


def test_build_draft_group_start_map_empty():
    assert build_draft_group_start_map([], set()) == {}


def test_valid_date_rejects_invalid():
    with pytest.raises(argparse.ArgumentTypeError):
        valid_date("bad")


def test_get_salary_date():
    date_val = get_salary_date({"StartDateEst": "2024-02-01T12:30:00.000-05:00"})
    assert date_val == datetime.date(2024, 2, 1)


def test_is_time_between_crosses_midnight():
    begin = datetime.time(23, 0)
    end = datetime.time(1, 0)
    assert is_time_between(begin, end, datetime.time(0, 30)) is True


def test_get_dk_lobby_uses_requests(monkeypatch):
    class DummySport(Sport):
        name = "NBA"

    class FakeResp:
        def json(self):
            return {"Contests": [], "DraftGroups": []}

    monkeypatch.setattr("dk_results.lobby.fetch.requests.get", lambda *_a, **_k: FakeResp())

    contests, draft_groups, resp = get_dk_lobby(DummySport, "http://example")
    assert contests == []
    assert draft_groups == []
    assert resp == {"Contests": [], "DraftGroups": []}


def test_is_time_between_standard_range():
    assert is_time_between(datetime.time(9, 0), datetime.time(17, 0), datetime.time(12, 0))
    assert not is_time_between(datetime.time(9, 0), datetime.time(17, 0), datetime.time(8, 0))
