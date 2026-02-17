from __future__ import annotations

import datetime

from classes.dfs_sheet_repository import DfsSheetRepository
from classes.dfs_sheet_service import DfsSheetService
from classes.sheets_service import build_dfs_sheet_service
from dfs_common.sheets import SheetClient


class FakeService:
    def __init__(self, values_by_range=None, sheets_metadata=None):
        self.values_by_range = values_by_range or {}
        self.sheets_metadata = sheets_metadata or []
        self.updated = []
        self.cleared = []
        self.gets = []
        self._action = None
        self._range = None
        self._body = None

    def spreadsheets(self):
        return self

    def values(self):
        return self

    def get(self, spreadsheetId=None, range=None):
        self._action = "get"
        self._range = range
        return self

    def update(self, spreadsheetId=None, range=None, valueInputOption=None, body=None):
        self._action = "update"
        self._range = range
        self._body = body
        return self

    def clear(self, spreadsheetId=None, range=None, body=None):
        self._action = "clear"
        self._range = range
        return self

    def execute(self):
        if self._action == "get":
            if self._range is None:
                return {"sheets": self.sheets_metadata}
            self.gets.append(self._range)
            return {"values": self.values_by_range.get(self._range, [])}
        if self._action == "update":
            self.updated.append((self._range, self._body))
            updated_cells = sum(len(row) for row in (self._body or {}).get("values", []))
            return {"updatedCells": updated_cells}
        if self._action == "clear":
            self.cleared.append(self._range)
            return {"clearedRange": self._range}
        raise AssertionError("Unexpected action")


def _make_service(sport, values_by_range=None):
    service = FakeService(values_by_range=values_by_range)
    client = SheetClient(spreadsheet_id="sheet-id", service=service)
    repo = DfsSheetRepository(client)
    return DfsSheetService(repo, sport), service


def test_service_init_and_get_players():
    values_by_range = {
        "NBA!A1:H1": [["Name", "Other"]],
        "NBA!A2:H": [["Alice", "x"], ["Bob", "y"]],
    }
    sheet, _service = _make_service("NBA", values_by_range=values_by_range)

    assert sheet.get_players() == ["Alice", "Bob"]


def test_service_clear_and_write_methods():
    values_by_range = {
        "NBA!A1:H1": [["Name"]],
        "NBA!A2:H": [["Alice"]],
    }
    sheet, service = _make_service("NBA", values_by_range=values_by_range)

    sheet.clear_standings()
    sheet.clear_lineups()
    sheet.write_players([["A"]])
    sheet.write_column("F", [["B"]])
    sheet.write_columns("F", "J", [["C", "D", "E", "F", "G"]])

    assert service.cleared == ["NBA!A2:H", "NBA!J3:W999"]
    assert service.updated[0][0] == "NBA!A2:H"
    assert service.updated[1][0] == "NBA!F2:F"
    assert service.updated[2][0] == "NBA!F2:J"


def test_service_header_writes():
    values_by_range = {
        "NBA!A1:H1": [["Name"]],
        "NBA!A2:H": [["Alice"]],
    }
    sheet, service = _make_service("NBA", values_by_range=values_by_range)

    sheet.add_last_updated(datetime.datetime(2024, 1, 2, 3, 4, 5))
    sheet.add_contest_details("Contest", 10)
    sheet.add_min_cash(5)
    sheet.add_non_cashing_info([["A", "B"]])
    sheet.add_train_info([["C", "D"]])
    sheet.add_optimal_lineup([["E", "F"]])

    ranges = [call[0] for call in service.updated]
    assert "NBA!L1:Q1" in ranges
    assert "NBA!X1:Y1" in ranges
    assert "NBA!W1:W1" in ranges
    assert "NBA!X3:Y16" in ranges
    assert "NBA!AA4:AM11" in ranges
    assert "NBA!X25:AC35" in ranges


def test_write_vip_lineups_writes_range():
    values_by_range = {
        "NBA!A1:H1": [["Name"]],
        "NBA!A2:H": [["Alice"]],
    }
    sheet, service = _make_service("NBA", values_by_range=values_by_range)

    sheet.write_vip_lineups(
        [
            {
                "user": "vipA",
                "pmr": 1,
                "players": [],
            }
        ]
    )

    assert service.updated[0][0] == "NBA!J3:W999"


def test_build_dfs_sheet_service_uses_injected_service():
    service = FakeService()
    sheet = build_dfs_sheet_service("NBA", service=service, spreadsheet_id="sheet-id")

    sheet.write_column("A", [["X"]])

    assert service.updated[0][0] == "NBA!A2:A"
