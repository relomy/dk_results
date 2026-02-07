import datetime
import sys
import types
from types import SimpleNamespace
from typing import Any, cast

import pytest

from classes import dfssheet as dfssheet_module
from classes.player import Player


class _FakeCredentials:
    @staticmethod
    def from_service_account_file(*args, **kwargs):
        return object()


def _install_google_stubs():
    google_module = types.ModuleType("google")
    google_oauth2 = types.ModuleType("google.oauth2")
    google_service_account = types.ModuleType("google.oauth2.service_account")
    cast(Any, google_service_account).Credentials = _FakeCredentials

    googleapiclient = types.ModuleType("googleapiclient")
    googleapiclient_discovery = types.ModuleType("googleapiclient.discovery")
    cast(Any, googleapiclient_discovery).build = lambda *args, **kwargs: None

    cast(Any, google_module).oauth2 = google_oauth2
    cast(Any, google_oauth2).service_account = google_service_account
    cast(Any, googleapiclient).discovery = googleapiclient_discovery

    sys.modules.setdefault("google", google_module)
    sys.modules.setdefault("google.oauth2", google_oauth2)
    sys.modules.setdefault("google.oauth2.service_account", google_service_account)
    sys.modules.setdefault("googleapiclient", googleapiclient)
    sys.modules.setdefault("googleapiclient.discovery", googleapiclient_discovery)


class _FakeRequest:
    def __init__(self, response):
        self._response = response

    def execute(self):
        return self._response


class _FakeValuesResource:
    def __init__(self, data, recorder):
        self.data = data
        self.recorder = recorder

    def update(self, spreadsheetId, range, valueInputOption, body):
        payload = {
            "spreadsheetId": spreadsheetId,
            "range": range,
            "valueInputOption": valueInputOption,
            "body": body,
        }
        self.recorder.setdefault("updates", []).append(payload)
        self.recorder["update"] = payload
        updated_cells = sum(len(row) for row in body.get("values", []))
        return _FakeRequest({"updatedCells": updated_cells})

    def clear(self, spreadsheetId, range, body):
        self.recorder["clear"] = {
            "spreadsheetId": spreadsheetId,
            "range": range,
            "body": body,
        }
        return _FakeRequest({"clearedRange": range})

    def get(self, spreadsheetId, range):
        self.recorder.setdefault("get", []).append(
            {"spreadsheetId": spreadsheetId, "range": range}
        )
        return _FakeRequest({"values": self.data.get(range, [])})


class _FakeSpreadsheetsResource:
    def __init__(self, data, recorder, sheets=None):
        self.data = data
        self.recorder = recorder
        self.sheets = sheets or []

    def values(self):
        return _FakeValuesResource(self.data, self.recorder)

    def get(self, spreadsheetId):
        return _FakeRequest({"sheets": self.sheets})


class _FakeService:
    def __init__(self, data, recorder, sheets=None):
        self.data = data
        self.recorder = recorder
        self.sheets = sheets or []

    def spreadsheets(self):
        return _FakeSpreadsheetsResource(self.data, self.recorder, self.sheets)


@pytest.fixture
def fake_sheet_service(monkeypatch):
    _install_google_stubs()
    from classes import dfssheet as dfssheet_module

    data = {
        "NBA!A1:H1": [
            [
                "Name",
                "Pos",
                "Team",
                "Matchup",
                "Salary",
                "Own",
                "Pts",
                "Value",
            ]
        ],
        "NBA!A2:H": [["Player1", "PG", "AAA", "vs BBB", "5000", "0.1", "10", "2"]],
        "NBA!J3:V61": [["lineup"]],
        "GOLF!A1:E1": [["Name", "Salary", "Pts", "Value", "Own"]],
        "GOLF!A2:E": [["Golfer", "10000", "80", "8", "0.2"]],
        "GOLF!L8:Z56": [["golf"]],
    }
    recorder = {}
    service = _FakeService(
        data,
        recorder,
        sheets=[
            {"properties": {"title": "NBA", "sheetId": 10}},
            {"properties": {"title": "GOLF", "sheetId": 20}},
        ],
    )
    monkeypatch.setattr(
        dfssheet_module,
        "service_account_provider",
        lambda *args, **kwargs: (lambda: service),
    )
    monkeypatch.setenv("SPREADSHEET_ID", "sheet123")
    return service, recorder


@pytest.fixture
def sheet_classes(fake_sheet_service):
    from classes.dfssheet import DFSSheet, Sheet

    return DFSSheet, Sheet


def _make_player(name="P1", pos="PG"):
    player = Player(name, pos, pos, 5000, "AAA@BBB 7:00PM", "AAA")
    player.ownership = 0.25
    player.fpts = 42.5
    player.value = 8.5
    return player


def test_sheet_find_sheet_id(sheet_classes):
    _, Sheet = sheet_classes
    sheet = Sheet()
    assert sheet.find_sheet_id("NBA") == 10
    assert sheet.find_sheet_id("Missing") is None


def test_sheet_write_values_and_clear(fake_sheet_service, sheet_classes):
    _, Sheet = sheet_classes
    sheet = Sheet()
    sheet.write_values_to_sheet_range([["a", "b"]], "NBA!A2:B2")
    sheet.clear_sheet_range("NBA!A2:B2")

    recorder = fake_sheet_service[1]
    assert recorder["update"]["range"] == "NBA!A2:B2"
    assert recorder["clear"]["range"] == "NBA!A2:B2"


def test_sheet_write_values_delegates_to_client(monkeypatch):
    from classes import dfssheet as dfssheet_module
    from dfs_common import sheets as common_sheets

    calls = {}

    def fake_write(self, values, cell_range, value_input_option="USER_ENTERED"):
        calls["values"] = values
        calls["range"] = cell_range
        calls["option"] = value_input_option

    monkeypatch.setattr(common_sheets.SheetClient, "write_values", fake_write)
    monkeypatch.setenv("SPREADSHEET_ID", "sheet123")
    sheet = dfssheet_module.Sheet()

    sheet.write_values_to_sheet_range([["a"]], "NBA!A1")

    assert calls["range"] == "NBA!A1"
    assert calls["option"] == "USER_ENTERED"


def test_sheet_get_values(sheet_classes):
    _, Sheet = sheet_classes
    sheet = Sheet()
    values = sheet.get_values_from_range("NBA!A1:H1")
    assert values == [
        ["Name", "Pos", "Team", "Matchup", "Salary", "Own", "Pts", "Value"]
    ]


def test_dfssheet_init_and_get_players(sheet_classes):
    DFSSheet, _ = sheet_classes
    sheet = DFSSheet("NBA")
    assert sheet.get_players() == ["Player1"]


def test_dfssheet_lineup_range_calls(fake_sheet_service, sheet_classes):
    DFSSheet, _ = sheet_classes
    sheet = DFSSheet("NBA")
    sheet.clear_lineups()
    sheet.write_lineup_range([["x"]])
    values = sheet.get_lineup_values()
    assert values == [["lineup"]]


def test_dfssheet_vip_lineups_non_golf(fake_sheet_service, sheet_classes):
    DFSSheet, _ = sheet_classes
    sheet = DFSSheet("NBA")
    vips = []
    for idx in range(6):
        vip = SimpleNamespace(
            name=f"user{idx}",
            pmr=1.1,
            rank=idx + 1,
            pts=100.0,
            lineup=[_make_player(name=f"P{idx}", pos="PG")],
        )
        vips.append(vip)

    sheet.write_vip_lineups(vips)
    recorder = fake_sheet_service[1]
    assert recorder["update"]["range"].startswith("NBA!")


def test_dfssheet_vip_lineups_golf(fake_sheet_service, sheet_classes):
    DFSSheet, _ = sheet_classes
    sheet = DFSSheet("GOLF")
    vip = SimpleNamespace(
        name="golfer",
        pmr=2.2,
        rank=1,
        pts=200.0,
        lineup=[_make_player(name="G1", pos="G")],
    )
    sheet.write_vip_lineups([vip])
    recorder = fake_sheet_service[1]
    assert recorder["update"]["range"].startswith("GOLF!")


def test_dfssheet_write_new_vip_lineups(fake_sheet_service, sheet_classes):
    DFSSheet, _ = sheet_classes
    sheet = DFSSheet("NBA")
    vip_lineups = [
        {
            "user": "alpha",
            "pmr": 1.0,
            "rank": 1,
            "pts": 100,
            "players": [
                {"pos": "PG", "name": "A", "valueIcon": "fire"},
                {"pos": "SG", "name": "B", "valueIcon": "ice"},
            ],
        }
    ]
    sheet.write_new_vip_lineups(vip_lineups)
    recorder = fake_sheet_service[1]
    assert recorder["update"]["range"].startswith("NBA!")


def test_dfssheet_missing_range_raises(sheet_classes):
    DFSSheet, _ = sheet_classes
    sheet = DFSSheet.__new__(DFSSheet)
    sheet.sport = "UNKNOWN"
    with pytest.raises(KeyError):
        sheet._resolve_lineup_range(new=False)


def test_dfssheet_metadata_writes(fake_sheet_service, sheet_classes):
    DFSSheet, _ = sheet_classes
    sheet = DFSSheet("NBA")
    sheet.add_last_updated(datetime.datetime(2024, 1, 1, 12, 0, 0))
    sheet.add_contest_details("Contest Name", 100)
    sheet.add_min_cash(150.5)
    sheet.add_non_cashing_info([["Label", "Value"]])
    sheet.add_train_info([["Rank", "Users"]])
    sheet.add_optimal_lineup([["Pos", "Name"]])

    ranges = [entry["range"] for entry in fake_sheet_service[1]["updates"]]
    assert "NBA!L1:Q1" in ranges
    assert "NBA!X1:Y1" in ranges
    assert "NBA!W1:W1" in ranges
    assert "NBA!X3:Y16" in ranges
    assert "NBA!AA4:AM11" in ranges
    assert "NBA!X25:AC35" in ranges


def test_dfssheet_write_columns_and_players(fake_sheet_service, sheet_classes):
    DFSSheet, _ = sheet_classes
    sheet = DFSSheet("NBA")
    sheet.write_column("I", [["a"], ["b"]])
    sheet.write_columns("J", "K", [["c", "d"]])
    sheet.write_players([["P1", "PG"]])
    sheet.clear_standings()

    updates = fake_sheet_service[1]["updates"]
    ranges = [entry["range"] for entry in updates]
    assert "NBA!I2:I" in ranges
    assert "NBA!J2:K" in ranges
    assert "NBA!A2:H" in ranges
    assert fake_sheet_service[1]["clear"]["range"] == "NBA!A2:H"


def test_dfssheet_build_values_for_vip_lineup(fake_sheet_service, sheet_classes):
    DFSSheet, _ = sheet_classes
    sheet = DFSSheet("NBA")
    vip = SimpleNamespace(
        name="vip",
        pmr=1.0,
        rank=2,
        pts=150.0,
        lineup=[_make_player(name="P1", pos="PG")],
    )

    values = sheet.build_values_for_vip_lineup(vip)
    assert values[0][:3] == ["vip", None, "PMR"]
    assert values[1] == ["Pos", "Name", "Salary", "Pts", "Value", "Own"]

    golf_sheet = DFSSheet("GOLF")
    golf_values = golf_sheet.build_values_for_vip_lineup(vip)
    assert golf_values[1] == ["Name", "Salary", "Pts", "Value", "Own", "Pos", "Score"]


def test_dfssheet_build_values_for_new_vip_lineup(fake_sheet_service, sheet_classes):
    DFSSheet, _ = sheet_classes
    sheet = DFSSheet("NBA")
    user = {"user": "alpha", "pmr": 1.0, "rank": 1, "pts": 200}
    players = [
        {"pos": "PG", "name": "A", "valueIcon": "fire"},
        {"pos": "SG", "name": "B", "valueIcon": "ice"},
        {"pos": "SF", "name": "C"},
    ]
    values = sheet.build_values_for_new_vip_lineup(user, players)
    assert values[1] == [
        "Pos",
        "Name",
        "Own",
        "Salary",
        "Pts",
        "Value",
        "RT Proj",
        "Time",
        "Stats",
    ]
    assert values[2][1] == "A 🔥"
    assert values[3][1] == "B ❄️"


def test_sheet_setup_service_uses_credentials(monkeypatch):
    captured = {}

    def fake_provider(path, scopes=None):
        captured["path"] = path
        captured["scopes"] = list(scopes or [])

        def _service():
            return "service"

        return _service

    monkeypatch.setattr(dfssheet_module, "service_account_provider", fake_provider)

    sheet = dfssheet_module.Sheet()
    service = sheet.setup_service()

    assert service == "service"
    assert captured["path"].endswith("client_secret.json")

def test_fetch_sheet_gids_filters_entries(monkeypatch):
    captured = {}

    def fake_get_sheet_gids(service, spreadsheet_id):
        captured["service"] = service
        captured["spreadsheet_id"] = spreadsheet_id
        return {"NBA": 10}

    monkeypatch.setattr(dfssheet_module.Sheet, "setup_service", lambda self: "service")
    monkeypatch.setattr(dfssheet_module, "get_sheet_gids", fake_get_sheet_gids)

    gids = dfssheet_module.fetch_sheet_gids("sheet")

    assert gids == {"NBA": 10}
    assert captured == {"service": "service", "spreadsheet_id": "sheet"}
