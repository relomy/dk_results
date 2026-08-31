"""Read-only inventory of a Google Sheet's live formatting.

Pulls the full formatting tree (number formats, bold, background color,
conditional format rules, merges, data validation, and formula cells) for a
set of tabs via the Sheets API and condenses it into a per-column report.
Used to snapshot what's actually live in a sheet before scoping formatting
work, instead of eyeballing the sheet and guessing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

FIELDS = (
    "sheets("
    "properties(title,sheetId),"
    "data(rowData(values(userEnteredValue.formulaValue,userEnteredFormat,dataValidation))),"
    "conditionalFormats,"
    "merges,"
    "bandedRanges"
    ")"
)


@dataclass(frozen=True)
class FormatRun:
    column: str
    row_range: str
    number_format: str | None
    bold: bool
    background: str | None


@dataclass(frozen=True)
class SheetFormatSummary:
    title: str
    format_runs: list[FormatRun]
    formula_cells: list[str]
    data_validations: list[str]
    conditional_formats: list[str]
    merges: list[str]


def fetch_raw_formatting(service: Any, spreadsheet_id: str, sheet_titles: list[str]) -> dict[str, Any]:
    return service.spreadsheets().get(spreadsheetId=spreadsheet_id, ranges=sheet_titles, fields=FIELDS).execute()


def _column_letters(index: int) -> str:
    letters = ""
    index += 1
    while index > 0:
        index, remainder = divmod(index - 1, 26)
        letters = chr(ord("A") + remainder) + letters
    return letters


def _rgb_hex(color: dict[str, float] | None) -> str | None:
    if not color:
        return None
    channels = (color.get("red", 0.0), color.get("green", 0.0), color.get("blue", 0.0))
    return "#" + "".join(f"{round(channel * 255):02x}" for channel in channels)


def _cell_signature(cell: dict[str, Any]) -> tuple[str | None, bool, str | None]:
    cell_format = cell.get("userEnteredFormat") or {}
    number_format = cell_format.get("numberFormat", {}).get("pattern")
    bold = bool(cell_format.get("textFormat", {}).get("bold", False))
    background = _rgb_hex(cell_format.get("backgroundColor"))
    return number_format, bold, background


def _cell_formula(cell: dict[str, Any]) -> str | None:
    return cell.get("userEnteredValue", {}).get("formulaValue")


def _cell_validation(cell: dict[str, Any]) -> str | None:
    validation = cell.get("dataValidation")
    if not validation:
        return None
    condition = validation.get("condition", {})
    return condition.get("type")


def _column_signatures(row_data: list[dict[str, Any]], col_index: int) -> list[tuple[str | None, bool, str | None]]:
    signatures = []
    for row in row_data:
        values = row.get("values") or []
        cell = values[col_index] if col_index < len(values) else {}
        signatures.append(_cell_signature(cell))
    return signatures


def _group_runs(column: str, signatures: list[tuple[str | None, bool, str | None]]) -> list[FormatRun]:
    runs: list[FormatRun] = []
    run_start: int | None = None
    run_signature: tuple[str | None, bool, str | None] | None = None
    for row_index, signature in enumerate([*signatures, None]):
        is_blank = signature is None or signature == (None, False, None)
        if signature == run_signature:
            continue
        if run_start is not None:
            row_range = f"{run_start + 1}" if row_index - 1 == run_start else f"{run_start + 1}:{row_index}"
            number_format, bold, background = run_signature
            runs.append(FormatRun(column, row_range, number_format, bold, background))
        run_start = None if is_blank else row_index
        run_signature = None if is_blank else signature
    return runs


def _max_columns(row_data: list[dict[str, Any]]) -> int:
    return max((len(row.get("values") or []) for row in row_data), default=0)


def summarize_grid(row_data: list[dict[str, Any]]) -> list[FormatRun]:
    runs: list[FormatRun] = []
    for col_index in range(_max_columns(row_data)):
        column = _column_letters(col_index)
        signatures = _column_signatures(row_data, col_index)
        runs.extend(_group_runs(column, signatures))
    return runs


def summarize_formula_cells(row_data: list[dict[str, Any]]) -> list[str]:
    cells = []
    for row_index, row in enumerate(row_data):
        for col_index, cell in enumerate(row.get("values") or []):
            formula = _cell_formula(cell)
            if formula:
                cells.append(f"{_column_letters(col_index)}{row_index + 1}: {formula}")
    return cells


def summarize_data_validations(row_data: list[dict[str, Any]]) -> list[str]:
    cells = []
    for row_index, row in enumerate(row_data):
        for col_index, cell in enumerate(row.get("values") or []):
            validation = _cell_validation(cell)
            if validation:
                cells.append(f"{_column_letters(col_index)}{row_index + 1}: {validation}")
    return cells


def _grid_range_a1(grid_range: dict[str, Any]) -> str:
    start_col = _column_letters(grid_range.get("startColumnIndex", 0))
    end_col = _column_letters(max(grid_range.get("endColumnIndex", 1) - 1, 0))
    start_row = grid_range.get("startRowIndex", 0) + 1
    end_row = grid_range.get("endRowIndex", start_row)
    return f"{start_col}{start_row}:{end_col}{end_row}"


def summarize_conditional_formats(raw_formats: list[dict[str, Any]]) -> list[str]:
    summaries = []
    for entry in raw_formats:
        ranges = ", ".join(_grid_range_a1(r) for r in entry.get("ranges", []))
        rule = entry.get("booleanRule") or entry.get("gradientRule") or {}
        kind = "boolean" if "booleanRule" in entry else "gradient"
        condition = rule.get("condition", {}).get("type", "") if kind == "boolean" else "gradient"
        summaries.append(f"{ranges}: {kind} ({condition})")
    return summaries


def summarize_merges(raw_merges: list[dict[str, Any]]) -> list[str]:
    return [_grid_range_a1(m) for m in raw_merges]


def summarize_sheet(sheet: dict[str, Any]) -> SheetFormatSummary:
    title = sheet.get("properties", {}).get("title", "")
    row_data = sheet.get("data", [{}])[0].get("rowData", []) if sheet.get("data") else []
    return SheetFormatSummary(
        title=title,
        format_runs=summarize_grid(row_data),
        formula_cells=summarize_formula_cells(row_data),
        data_validations=summarize_data_validations(row_data),
        conditional_formats=summarize_conditional_formats(sheet.get("conditionalFormats", [])),
        merges=summarize_merges(sheet.get("merges", [])),
    )


def summarize_spreadsheet(raw: dict[str, Any]) -> list[SheetFormatSummary]:
    return [summarize_sheet(sheet) for sheet in raw.get("sheets", [])]


def _render_format_runs(runs: list[FormatRun]) -> list[str]:
    lines = ["### Number format / bold / background runs"]
    if not runs:
        lines.append("(none)")
        return lines
    for run in runs:
        parts = []
        if run.number_format:
            parts.append(f"format=`{run.number_format}`")
        if run.bold:
            parts.append("bold")
        if run.background:
            parts.append(f"background={run.background}")
        lines.append(f"- {run.column}{run.row_range}: {', '.join(parts)}")
    return lines


def _render_list(heading: str, items: list[str]) -> list[str]:
    lines = [f"### {heading}"]
    if items:
        lines.extend(f"- {item}" for item in items)
    else:
        lines.append("(none)")
    return lines


def render_markdown(summaries: list[SheetFormatSummary]) -> str:
    lines: list[str] = ["# Sheet formatting snapshot", ""]
    for summary in summaries:
        lines.append(f"## {summary.title}")
        lines.extend(_render_format_runs(summary.format_runs))
        lines.append("")
        lines.extend(_render_list("Conditional format rules", summary.conditional_formats))
        lines.append("")
        lines.extend(_render_list("Merged ranges", summary.merges))
        lines.append("")
        lines.extend(_render_list("Data validation cells", summary.data_validations))
        lines.append("")
        lines.extend(_render_list("Formula cells", summary.formula_cells))
        lines.append("")
    return "\n".join(lines)
