"""Pure helpers for DFS sheet ranges and value formatting."""

import re
from dataclasses import dataclass
from typing import Any

from dfs_common.sheets import NumberFormat

from .sport import get_lineup_range

START_COL = "A"

# Column offset of "Salary" within a VIP lineup block, relative to the
# block's own top-left cell (see build_values_for_vip_lineup).
_VIP_LINEUP_SALARY_COL = 3

_RANGE_RE = re.compile(r"^(?P<sheet>[^!]+)!(?P<start_col>[A-Z]+)(?P<start_row>\d+)(?::(?P<end_col>[A-Z]+)\d*)?$")


@dataclass(frozen=True)
class CellFormat:
    """A number format to apply to one cell, positioned relative to a value grid's top-left."""

    row: int
    col: int
    number_format: NumberFormat


@dataclass(frozen=True)
class RangeOrigin:
    """The sheet, start cell, and end column of a `Sheet!A1:B2`-style range."""

    sheet: str
    start_col: str
    start_row: int
    end_col: str


def parse_range(cell_range: str) -> RangeOrigin:
    """Parse a `Sheet!A1:B2`-style range into its sheet, start cell, and end column."""
    match = _RANGE_RE.match(cell_range)
    if not match:
        raise ValueError(f"cannot parse range {cell_range!r}")
    end_col = match.group("end_col") or match.group("start_col")
    return RangeOrigin(
        sheet=match.group("sheet"),
        start_col=match.group("start_col"),
        start_row=int(match.group("start_row")),
        end_col=end_col,
    )


def end_col_for_sport(sport: str) -> str:
    if "PGA" in sport or sport == "GOLF":
        return "E"
    return "H"


def data_range_for_sport(sport: str) -> str:
    end_col = end_col_for_sport(sport)
    return f"{sport}!{START_COL}2:{end_col}"


def header_range_for_sport(sport: str) -> str:
    end_col = end_col_for_sport(sport)
    return f"{sport}!{START_COL}1:{end_col}1"


def lineup_range_for_sport(sport: str) -> str:
    lineup_range = get_lineup_range(sport)
    if not lineup_range:
        raise KeyError(f"Missing lineup range for sport '{sport}'")
    return f"{sport}!{lineup_range}"


def build_values_for_vip_lineup(
    user: dict[str, Any], players: list[dict[str, Any]]
) -> tuple[list[list[Any]], list[CellFormat]]:
    values: list[list[Any]] = [[user["user"], None, "PMR", user["pmr"], None, None, None, None]]
    values.append(["Pos", "Name", "Own", "Salary", "Pts", "Value", "RT Proj", "Time", "Stats"])
    format_plan: list[CellFormat] = []
    for player in players:
        name = player.get("name", "") or ""
        value_icon = player.get("valueIcon")
        if value_icon == "fire":
            name += " 🔥"
        elif value_icon == "ice":
            name += " ❄️"
        format_plan.append(CellFormat(row=len(values), col=_VIP_LINEUP_SALARY_COL, number_format=NumberFormat.CURRENCY))
        values.append(
            [
                player.get("pos", ""),
                name,
                player.get("ownership", ""),
                player.get("salary", ""),
                player.get("pts", ""),
                player.get("value", ""),
                player.get("rtProj", ""),
                player.get("timeStatus", ""),
                player.get("stats", ""),
            ]
        )
    format_plan.append(CellFormat(row=len(values), col=_VIP_LINEUP_SALARY_COL, number_format=NumberFormat.CURRENCY))
    values.append(
        [
            "rank",
            user.get("rank", ""),
            None,
            user.get("salary", ""),
            user.get("pts", ""),
            None,
            None,
            None,
        ]
    )
    return values, format_plan
