"""Service layer for DFS sheet operations."""

import datetime
from typing import Any, Sequence

from dfs_common.sheets import NumberFormat

from dk_results.domain.dfs_sheet_domain import (
    build_values_for_vip_lineup,
    data_range_for_sport,
    header_range_for_sport,
    lineup_range_for_sport,
    parse_range,
)

from .dfs_sheet_repository import DfsSheetRepository

# Width of a VIP lineup block's widest row (the "Pos Name Own Salary Pts
# Value RT Proj Time Stats" header row). The blank row separating blocks is
# padded to this width so every row in the write stays wide enough for the
# Salary column's format range to resolve against.
_VIP_LINEUP_ROW_WIDTH = 9


class DfsSheetService:
    """Sheet operations for DFS lineups and standings."""

    def __init__(self, repo: DfsSheetRepository, sport: str) -> None:
        self.repo = repo
        self.sport = sport
        self.data_range = data_range_for_sport(sport)
        self.columns: list[str] | None = None
        self.values: list[list[Any]] | None = None

    def _ensure_loaded(self) -> None:
        if self.columns is None:
            self.columns = self.repo.read_range(header_range_for_sport(self.sport))[0]
        if self.values is None:
            self.values = self.repo.read_range(self.data_range)

    def find_sheet_id(self, title: str, *, partial: bool = False) -> int | None:
        return self.repo.find_sheet_id(title, partial=partial)

    def clear_standings(self) -> None:
        self.repo.clear_range(self.data_range)

    def clear_lineups(self) -> None:
        self.repo.clear_range(lineup_range_for_sport(self.sport))

    def write_players(self, values: Sequence[Sequence[Any]]) -> None:
        self.repo.write_range(values, self.data_range)

    def write_column(self, column: str, values: Sequence[Sequence[Any]], start_row: int = 2) -> None:
        cell_range = f"{self.sport}!{column}{start_row}:{column}"
        self.repo.write_range(values, cell_range)

    def write_columns(
        self,
        start_col: str,
        end_col: str,
        values: Sequence[Sequence[Any]],
        start_row: int = 2,
    ) -> None:
        cell_range = f"{self.sport}!{start_col}{start_row}:{end_col}"
        self.repo.write_range(values, cell_range)

    def add_last_updated(self, dt_updated: datetime.datetime) -> None:
        cell_range = f"{self.sport}!L1:Q1"
        values = [["Last Updated", "", dt_updated.strftime("%Y-%m-%d %H:%M:%S")]]
        self.repo.write_range(values, cell_range)

    def add_contest_details(self, contest_name: str, positions_paid: int | None) -> None:
        cell_range = f"{self.sport}!X1:Y1"
        values = [[positions_paid, contest_name]]
        self.repo.write_range(values, cell_range)

    def add_min_cash(self, min_cash: int | float) -> None:
        cell_range = f"{self.sport}!W1:W1"
        values = [[min_cash]]
        self.repo.write_range(values, cell_range)

    def add_non_cashing_info(self, non_cashing_info: list[list[Any]]) -> None:
        cell_range = f"{self.sport}!X3:Y16"
        self.repo.write_range(non_cashing_info, cell_range)

    @staticmethod
    def _column_letters_to_index(column: str) -> int:
        index = 0
        for char in column:
            index = index * 26 + (ord(char) - ord("A") + 1)
        return index

    @staticmethod
    def _column_index_to_letters(index: int) -> str:
        letters = ""
        while index > 0:
            index, remainder = divmod(index - 1, 26)
            letters = chr(ord("A") + remainder) + letters
        return letters

    def add_train_info(self, train_info: list[list[Any]]) -> None:
        start_col = "AA"
        min_columns = 13
        max_columns = max((len(row) for row in train_info), default=min_columns)
        total_columns = max(min_columns, max_columns)
        start_index = self._column_letters_to_index(start_col)
        end_col = self._column_index_to_letters(start_index + total_columns - 1)
        cell_range = f"{self.sport}!{start_col}4:{end_col}11"
        self.repo.write_range(train_info, cell_range)

    def add_optimal_lineup(self, optimal_lineup_info: list[list[Any]]) -> None:
        cell_range = f"{self.sport}!X25:AC35"
        self.repo.write_range(optimal_lineup_info, cell_range)

    def write_vip_lineups(self, vip_lineups: list[dict[str, Any]]) -> None:
        if not vip_lineups:
            return
        vip_lineups.sort(key=lambda x: x["user"].lower())
        origin = parse_range(lineup_range_for_sport(self.sport))
        start_col_index = self._column_letters_to_index(origin.start_col)

        all_lineup_values: list[list[Any]] = []
        all_formats: list[tuple[str, NumberFormat]] = []
        for vip_lineup in vip_lineups:
            values, format_plan = build_values_for_vip_lineup(vip_lineup, vip_lineup["players"])
            block_row_offset = len(all_lineup_values)
            for cell_format in format_plan:
                col_letters = self._column_index_to_letters(start_col_index + cell_format.col)
                row_number = origin.start_row + block_row_offset + cell_format.row
                all_formats.append((f"{col_letters}{row_number}", cell_format.number_format))
            values.append([None] * _VIP_LINEUP_ROW_WIDTH)
            all_lineup_values.extend(values)

        end_row = origin.start_row + len(all_lineup_values) - 1
        cell_range = f"{origin.sheet}!{origin.start_col}{origin.start_row}:{origin.end_col}{end_row}"
        self.repo.write_range_with_format(all_lineup_values, cell_range, all_formats)

    def get_players(self) -> list[str]:
        self._ensure_loaded()
        assert self.columns is not None
        assert self.values is not None
        return [row[self.columns.index("Name")] for row in self.values]
