from __future__ import annotations

import datetime

from dfs_common.sheets import NumberFormat, SheetClient

from dk_results.domain.dfs_sheet_domain import CellFormat
from dk_results.sheets.dfs_sheet_repository import DfsSheetRepository
from dk_results.sheets.dfs_sheet_service import DfsSheetService
from dk_results.sheets.sheets_service import build_dfs_sheet_service


class RecordingRepo:
    """Records calls to write_range_with_format without exercising SheetClient/Sheets API internals."""

    def __init__(self):
        self.write_range_with_format_calls = []
        self.write_range_calls = []

    def write_range_with_format(self, values, cell_range, formats):
        self.write_range_with_format_calls.append((values, cell_range, formats))

    def write_range(self, values, cell_range):
        self.write_range_calls.append((values, cell_range))


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


def _make_service(sport, values_by_range=None, sheets_metadata=None):
    service = FakeService(values_by_range=values_by_range, sheets_metadata=sheets_metadata)
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


def test_write_players_without_format_plan_uses_plain_write_range():
    values_by_range = {
        "NBA!A1:H1": [["Name"]],
        "NBA!A2:H": [["Alice"]],
    }
    sheet, service = _make_service("NBA", values_by_range=values_by_range)

    sheet.write_players([["A", 8000]])

    assert service.updated[-1][0] == "NBA!A2:H"


def test_write_players_with_format_plan_writes_values_with_format():
    repo = RecordingRepo()
    sheet = DfsSheetService(repo, "NBA")

    sheet.write_players(
        [
            ["PG", "Alpha", "TeamA", "vs. TeamB", 8000, 0.1, 50, 6.25],
            ["SG", "Beta", "TeamC", "at TeamD", 7000, 0.2, 40, 5.71],
        ],
        [
            CellFormat(row=0, col=4, number_format=NumberFormat.CURRENCY),
            CellFormat(row=1, col=4, number_format=NumberFormat.CURRENCY),
        ],
    )

    assert len(repo.write_range_with_format_calls) == 1
    values, cell_range, formats = repo.write_range_with_format_calls[0]
    # data_range_for_sport("NBA") is "NBA!A2:H"; 2 rows -> A2:H3.
    assert cell_range == "NBA!A2:H3"
    assert values[0][4] == 8000
    assert values[1][4] == 7000
    assert formats == [("E2", NumberFormat.CURRENCY), ("E3", NumberFormat.CURRENCY)]


def test_write_players_with_empty_format_plan_uses_plain_write_range():
    repo = RecordingRepo()
    sheet = DfsSheetService(repo, "NBA")

    sheet.write_players([], [])

    assert repo.write_range_with_format_calls == []
    assert repo.write_range_calls == [([], "NBA!A2:H")]


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


def test_write_vip_lineups_writes_values_with_format():
    repo = RecordingRepo()
    sheet = DfsSheetService(repo, "NBA")

    sheet.write_vip_lineups(
        [
            {
                "user": "vipA",
                "pmr": 1,
                "players": [],
            }
        ]
    )

    assert len(repo.write_range_with_format_calls) == 1
    values, cell_range, formats = repo.write_range_with_format_calls[0]
    # Block has no players: user row (3), header row (4), footer row (5),
    # blank separator (6) -> NBA!J3:W6.
    assert cell_range == "NBA!J3:W6"
    assert len(values) == 4
    assert formats == [("M5", NumberFormat.CURRENCY), ("N5", NumberFormat.DECIMAL(1))]


def test_write_vip_lineups_translates_format_plan_to_absolute_ranges():
    repo = RecordingRepo()
    sheet = DfsSheetService(repo, "NBA")

    sheet.write_vip_lineups(
        [
            {
                "user": "vipA",
                "pmr": 1,
                "rank": 1,
                "salary": 12000,
                "pts": 100,
                "players": [
                    {"pos": "PG", "name": "Alpha", "ownership": 0.1, "salary": 8000, "pts": 50},
                ],
            }
        ]
    )

    assert len(repo.write_range_with_format_calls) == 1
    values, cell_range, formats = repo.write_range_with_format_calls[0]

    # Rows: 0=user(J3), 1=header(J4), 2=Alpha(J5), 3=footer(J6), 4=blank(J7).
    # Column offsets from the block's start column (J): Own=2(L), Salary=3(M),
    # Pts=4(N), Value=5(O). The footer row has no Value cell.
    assert cell_range == "NBA!J3:W7"
    assert formats == [
        ("L5", NumberFormat.PERCENT),
        ("M5", NumberFormat.CURRENCY),
        ("N5", NumberFormat.DECIMAL(1)),
        ("O5", NumberFormat.DECIMAL(1)),
        ("M6", NumberFormat.CURRENCY),
        ("N6", NumberFormat.DECIMAL(1)),
    ]
    assert values[2][3] == 8000  # Alpha's Salary value
    assert values[3][3] == 12000  # footer's remaining-salary value


def test_write_vip_lineups_with_no_lineups_is_a_no_op():
    repo = RecordingRepo()
    sheet = DfsSheetService(repo, "NBA")

    sheet.write_vip_lineups([])

    assert repo.write_range_with_format_calls == []


def test_add_train_info_expands_range_for_wide_rows():
    values_by_range = {
        "MLB!A1:H1": [["Name"]],
        "MLB!A2:H": [["Alice"]],
    }
    sheet, service = _make_service("MLB", values_by_range=values_by_range)

    sheet.add_train_info(
        [
            [
                "Rank",
                "Users",
                "Score",
                "PMR",
                "P1",
                "P2",
                "P3",
                "P4",
                "P5",
                "P6",
                "P7",
                "P8",
                "P9",
                "P10",
            ]
        ]
    )

    assert service.updated[0][0] == "MLB!AA4:AN11"


def test_build_dfs_sheet_service_uses_injected_service():
    service = FakeService()
    sheet = build_dfs_sheet_service("NBA", service=service, spreadsheet_id="sheet-id")

    sheet.write_column("A", [["X"]])

    assert service.updated[0][0] == "NBA!A2:A"
