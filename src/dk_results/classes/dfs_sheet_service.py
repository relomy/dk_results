"""Service layer for DFS sheet operations."""

import datetime
from typing import Any, Sequence

from .dfs_sheet_domain import (
    build_values_for_vip_lineup,
    data_range_for_sport,
    header_range_for_sport,
    lineup_range_for_sport,
)
from .dfs_sheet_repository import DfsSheetRepository


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

    def add_train_info(self, train_info: list[list[Any]]) -> None:
        cell_range = f"{self.sport}!AA4:AM11"
        self.repo.write_range(train_info, cell_range)

    def add_optimal_lineup(self, optimal_lineup_info: list[list[Any]]) -> None:
        cell_range = f"{self.sport}!X25:AC35"
        self.repo.write_range(optimal_lineup_info, cell_range)

    def write_vip_lineups(self, vip_lineups: list[dict[str, Any]]) -> None:
        vip_lineups.sort(key=lambda x: x["user"].lower())
        all_lineup_values: list[list[Any]] = []
        for vip_lineup in vip_lineups:
            values = build_values_for_vip_lineup(vip_lineup, vip_lineup["players"])
            values.append([])
            all_lineup_values.extend(values)
        self.repo.write_range(all_lineup_values, lineup_range_for_sport(self.sport))

    def get_players(self) -> list[str]:
        self._ensure_loaded()
        assert self.columns is not None
        assert self.values is not None
        return [row[self.columns.index("Name")] for row in self.values]
