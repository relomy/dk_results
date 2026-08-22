"""Repository wrapper for SheetClient operations."""

from collections.abc import Sequence
from typing import Any

from dfs_common.sheets import SheetClient


class DfsSheetRepository:
    def __init__(self, client: SheetClient) -> None:
        self._client = client

    def read_range(self, cell_range: str) -> list[list[Any]]:
        return self._client.get_values(cell_range)

    def write_range(self, values: Sequence[Sequence[Any]], cell_range: str) -> None:
        self._client.write_values([list(row) for row in values], cell_range, value_input_option="USER_ENTERED")

    def clear_range(self, cell_range: str) -> None:
        self._client.clear_range(cell_range)

    def find_sheet_id(self, title: str, *, partial: bool = False) -> int | None:
        return self._client.find_sheet_id(title, partial=partial)
