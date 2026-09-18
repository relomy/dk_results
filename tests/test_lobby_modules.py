import logging.config
import runpy
import sys
import types

import pytest

from dk_results.domain.sport import Sport
from dk_results.lobby.fetch import (
    get_dk_lobby,
    get_lobby_response,
    load_sport_class_contests,
    requests_fetch_json,
)


def _contest_payload(dk_id: int, *, entries: int = 200, fee: int = 10):
    return {
        "sd": "1700000000000",
        "n": "Contest",
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


def test_import_find_new_double_ups_has_no_runtime_side_effects(monkeypatch):
    calls = {"dotenv": 0, "logging": 0, "cookies": 0}

    fake_cookies = types.ModuleType("dk_results.draftkings.cookies")

    def fake_get_dk_cookies(*_args, **_kwargs):
        calls["cookies"] += 1
        return ({}, {})

    fake_cookies.get_dk_cookies = fake_get_dk_cookies

    fake_contestdatabase = types.ModuleType("dk_results.persistence.contestdatabase")

    class FakeContestDatabase:
        def __init__(self, *_args, **_kwargs):
            pass

    fake_contestdatabase.ContestDatabase = FakeContestDatabase

    monkeypatch.setitem(sys.modules, "dk_results.draftkings.cookies", fake_cookies)
    monkeypatch.setitem(sys.modules, "dk_results.persistence.contestdatabase", fake_contestdatabase)
    monkeypatch.setattr(
        "dotenv.load_dotenv",
        lambda *_args, **_kwargs: calls.__setitem__("dotenv", calls["dotenv"] + 1),
    )
    monkeypatch.setattr(
        logging.config,
        "fileConfig",
        lambda *_args, **_kwargs: calls.__setitem__("logging", calls["logging"] + 1),
    )

    runpy.run_module("find_new_double_ups", run_name="find_new_double_ups_import_probe")

    assert calls == {"dotenv": 0, "logging": 0, "cookies": 0}


def test_get_dk_lobby_uses_injected_fetch_json():
    captured = {}

    class DummySport(Sport):
        name = "NFL"

    def fake_fetch_json(url, headers, cookies):
        captured["url"] = url
        captured["headers"] = headers
        captured["cookies"] = cookies
        return {"Contests": [{"id": 10}], "DraftGroups": []}

    contests, draft_groups, response = get_dk_lobby(
        DummySport,
        "https://www.draftkings.com/lobby/getcontests?sport=NFL",
        fetch_json=fake_fetch_json,
        headers={"X-Requested-With": "XMLHttpRequest"},
        cookies={"session": "abc"},
    )

    assert captured["url"].endswith("sport=NFL")
    assert captured["headers"]["X-Requested-With"] == "XMLHttpRequest"
    assert captured["cookies"] == {"session": "abc"}
    assert contests == [{"id": 10}]
    assert draft_groups == []
    assert response == {"Contests": [{"id": 10}], "DraftGroups": []}


def test_requests_fetch_json_passes_headers_and_cookies(monkeypatch):
    captured = {}

    class FakeResponse:
        def json(self):
            return {"ok": True}

    def fake_get(url, headers=None, cookies=None):
        captured["url"] = url
        captured["headers"] = headers
        captured["cookies"] = cookies
        return FakeResponse()

    monkeypatch.setattr("dk_results.lobby.fetch.requests.get", fake_get)

    result = requests_fetch_json(
        "https://www.example.com/lobby",
        {"X-Requested-With": "XMLHttpRequest"},
        {"session": "abc"},
    )

    assert result == {"ok": True}
    assert captured["url"] == "https://www.example.com/lobby"
    assert captured["headers"]["X-Requested-With"] == "XMLHttpRequest"
    assert captured["cookies"] == {"session": "abc"}


def test_get_lobby_response_uses_injected_client():
    class FakeClient:
        def __init__(self):
            self.calls = []

        def get_lobby_contests(self, sport, live=False):
            self.calls.append((sport, live))
            return {"Contests": []}

    client = FakeClient()
    result = get_lobby_response("NFL", live=True, dk_client=client)

    assert result == {"Contests": []}
    assert client.calls == [("NFL", True)]


@pytest.mark.parametrize("live", [False, True])
def test_get_lobby_response_default_client_never_authenticates(anonymous_lobby, live):
    payload = {"Contests": [], "DraftGroups": []}
    anonymous_lobby(payload)

    result = get_lobby_response("CFB", live=live)

    assert result == payload


class _RestrictedSport(Sport):
    name = "NFL"
    contest_restraint_game_type_id = 87


def _sport_class_response():
    return {
        "Contests": [
            {**_contest_payload(41), "dg": 41},
            {**_contest_payload(42), "dg": 42},
        ],
        "DraftGroups": [
            {
                "DraftGroupTag": "Featured",
                "ContestStartTimeSuffix": None,
                "DraftGroupId": 41,
                "StartDateEst": "2026-02-09T10:45:00.000-05:00",
                "ContestTypeId": 87,
                "GameTypeId": 87,
            },
            {
                "DraftGroupTag": "Featured",
                "ContestStartTimeSuffix": None,
                "DraftGroupId": 42,
                "StartDateEst": "2026-02-09T12:24:00.000-05:00",
                "ContestTypeId": 154,
                "GameTypeId": 154,
            },
        ],
    }


def test_load_sport_class_contests_filters_by_draft_groups_and_returns_featured_ids(monkeypatch):
    response = _sport_class_response()
    monkeypatch.setattr(
        "dk_results.lobby.fetch.get_lobby_response",
        lambda _sport, live=False: response,
    )

    contests, featured_draft_group_ids = load_sport_class_contests(_RestrictedSport)

    assert [contest["id"] for contest in contests] == [41]
    assert featured_draft_group_ids == {41, 42}


def test_load_sport_class_contests_uses_anonymous_lobby_path(anonymous_lobby):
    """Sport-class mode resolves draft groups without touching auth machinery (ADR-0009)."""
    anonymous_lobby(_sport_class_response())

    contests, featured_draft_group_ids = load_sport_class_contests(_RestrictedSport)

    assert [contest["id"] for contest in contests] == [41]
    assert featured_draft_group_ids == {41, 42}


def test_load_sport_class_contests_exits_on_invalid_shape(monkeypatch):
    monkeypatch.setattr(
        "dk_results.lobby.fetch.get_lobby_response",
        lambda _sport, live=False: {"Other": []},
    )

    with pytest.raises(SystemExit):
        load_sport_class_contests(_RestrictedSport)
