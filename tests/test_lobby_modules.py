import logging.config
import runpy
import sys
import types

from classes.contest import Contest
from classes.sport import Sport
from lobby.double_ups import get_stats
from lobby.fetch import get_dk_lobby, get_lobby_response, requests_fetch_json


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

    fake_cookieservice = types.ModuleType("classes.cookieservice")

    def fake_get_dk_cookies(*_args, **_kwargs):
        calls["cookies"] += 1
        return ({}, {})

    fake_cookieservice.get_dk_cookies = fake_get_dk_cookies

    fake_contestdatabase = types.ModuleType("classes.contestdatabase")

    class FakeContestDatabase:
        def __init__(self, *_args, **_kwargs):
            pass

    fake_contestdatabase.ContestDatabase = FakeContestDatabase

    monkeypatch.setitem(sys.modules, "classes.cookieservice", fake_cookieservice)
    monkeypatch.setitem(sys.modules, "classes.contestdatabase", fake_contestdatabase)
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


def test_get_stats_include_largest_for_interactive_use():
    contests = [
        Contest(_contest_payload(1, entries=120, fee=10), "NBA"),
        Contest(_contest_payload(2, entries=300, fee=10), "NBA"),
    ]

    stats = get_stats(contests, include_largest=True)
    date_key = contests[0].start_dt.strftime("%Y-%m-%d")

    assert stats[date_key]["count"] == 2
    assert stats[date_key]["dubs"][10]["count"] == 2
    assert stats[date_key]["dubs"][10]["largest"] == 300


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

    monkeypatch.setattr("lobby.fetch.requests.get", fake_get)

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


def test_get_lobby_response_constructs_default_client(monkeypatch):
    class FakeDraftkings:
        def get_lobby_contests(self, sport, live=False):
            return {"sport": sport, "live": live}

    monkeypatch.setattr("lobby.fetch.Draftkings", lambda: FakeDraftkings())

    result = get_lobby_response("NBA", live=False)

    assert result == {"sport": "NBA", "live": False}
