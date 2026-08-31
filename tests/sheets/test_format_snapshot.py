from __future__ import annotations

from dk_results.sheets.format_snapshot import (
    FormatRun,
    fetch_raw_formatting,
    render_markdown,
    summarize_conditional_formats,
    summarize_data_validations,
    summarize_formula_cells,
    summarize_grid,
    summarize_merges,
    summarize_sheet,
)


class FakeGetCall:
    def __init__(self, recorder, response):
        self._recorder = recorder
        self._response = response

    def execute(self):
        return self._response


class FakeSheetsService:
    def __init__(self, response):
        self._response = response
        self.get_calls = []

    def spreadsheets(self):
        return self

    def get(self, **kwargs):
        self.get_calls.append(kwargs)
        return FakeGetCall(self.get_calls, self._response)


def _cell(number_format=None, bold=False, background=None, formula=None, validation=None):
    cell = {}
    if number_format is not None or bold or background is not None:
        cell["userEnteredFormat"] = {}
        if number_format is not None:
            cell["userEnteredFormat"]["numberFormat"] = {"pattern": number_format}
        if bold:
            cell["userEnteredFormat"]["textFormat"] = {"bold": True}
        if background is not None:
            cell["userEnteredFormat"]["backgroundColor"] = background
    if formula is not None:
        cell["userEnteredValue"] = {"formulaValue": formula}
    if validation is not None:
        cell["dataValidation"] = {"condition": {"type": validation}}
    return cell


def test_fetch_raw_formatting_requests_named_sheets_with_fields_mask():
    service = FakeSheetsService(response={"sheets": []})
    fetch_raw_formatting(service, "sheet-id", ["NBA", "GOLF"])

    assert len(service.get_calls) == 1
    call = service.get_calls[0]
    assert call["spreadsheetId"] == "sheet-id"
    assert call["ranges"] == ["NBA", "GOLF"]
    assert "conditionalFormats" in call["fields"]
    assert "merges" in call["fields"]


def test_summarize_grid_collapses_consecutive_matching_cells_into_one_run():
    row_data = [
        {"values": [_cell(number_format="0.00%")]},
        {"values": [_cell(number_format="0.00%")]},
        {"values": [_cell(number_format="0.00%")]},
    ]

    runs = summarize_grid(row_data)

    assert runs == [FormatRun(column="A", row_range="1:3", number_format="0.00%", bold=False, background=None)]


def test_summarize_grid_starts_a_new_run_after_a_blank_gap_with_the_same_format():
    row_data = [
        {"values": [_cell(number_format="0.00%")]},
        {"values": [_cell()]},
        {"values": [_cell(number_format="0.00%")]},
    ]

    runs = summarize_grid(row_data)

    assert runs == [
        FormatRun(column="A", row_range="1", number_format="0.00%", bold=False, background=None),
        FormatRun(column="A", row_range="3", number_format="0.00%", bold=False, background=None),
    ]


def test_summarize_grid_distinguishes_bold_and_background_from_number_format():
    row_data = [
        {"values": [_cell(bold=True, background={"red": 1.0, "green": 0.0, "blue": 0.0})]},
    ]

    runs = summarize_grid(row_data)

    assert runs == [FormatRun(column="A", row_range="1", number_format=None, bold=True, background="#ff0000")]


def test_summarize_formula_cells_reports_a1_refs():
    row_data = [{"values": [_cell(), _cell(formula="=XLOOKUP(A1, B:B, C:C)")]}]

    assert summarize_formula_cells(row_data) == ["B1: =XLOOKUP(A1, B:B, C:C)"]


def test_summarize_data_validations_reports_condition_type():
    row_data = [{"values": [_cell(validation="ONE_OF_LIST")]}]

    assert summarize_data_validations(row_data) == ["A1: ONE_OF_LIST"]


def test_summarize_conditional_formats_reports_boolean_and_gradient_rules():
    raw = [
        {
            "ranges": [{"startRowIndex": 0, "endRowIndex": 5, "startColumnIndex": 3, "endColumnIndex": 4}],
            "booleanRule": {"condition": {"type": "NUMBER_GREATER"}},
        },
        {
            "ranges": [{"startRowIndex": 0, "endRowIndex": 5, "startColumnIndex": 3, "endColumnIndex": 4}],
            "gradientRule": {},
        },
    ]

    summaries = summarize_conditional_formats(raw)

    assert summaries == [
        "D1:D5: boolean (NUMBER_GREATER)",
        "D1:D5: gradient (gradient)",
    ]


def test_summarize_merges_reports_a1_ranges():
    raw = [{"startRowIndex": 0, "endRowIndex": 1, "startColumnIndex": 0, "endColumnIndex": 5}]

    assert summarize_merges(raw) == ["A1:E1"]


def test_summarize_sheet_combines_all_categories():
    sheet = {
        "properties": {"title": "NBA"},
        "data": [{"rowData": [{"values": [_cell(number_format="0.00%")]}]}],
        "conditionalFormats": [],
        "merges": [{"startRowIndex": 0, "endRowIndex": 1, "startColumnIndex": 0, "endColumnIndex": 2}],
    }

    summary = summarize_sheet(sheet)

    assert summary.title == "NBA"
    assert summary.format_runs == [
        FormatRun(column="A", row_range="1", number_format="0.00%", bold=False, background=None)
    ]
    assert summary.merges == ["A1:B1"]


def test_render_markdown_includes_each_sheet_and_falls_back_to_none():
    summary = summarize_sheet(
        {
            "properties": {"title": "GOLF"},
            "data": [{"rowData": []}],
            "conditionalFormats": [],
            "merges": [],
        }
    )

    report = render_markdown([summary])

    assert "## GOLF" in report
    assert "(none)" in report
