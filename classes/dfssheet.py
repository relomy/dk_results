import logging
import logging.config
import os
from datetime import datetime
from typing import Any

from dfs_common.sheets import SheetClient, get_sheet_gids, service_account_provider

from .sport import get_lineup_range, get_new_lineup_range

logging.config.fileConfig("logging.ini")


class Sheet:
    """Object to represent Google Sheet."""

    def __init__(self, logger: logging.Logger | None = None) -> None:
        self.logger = logger or logging.getLogger(__name__)

        # unique ID for DFS Ownership/Value spreadsheet
        self.spreadsheet_id = os.getenv("SPREADSHEET_ID")
        self._client = SheetClient(
            spreadsheet_id=self.spreadsheet_id,
            credentials_provider=self.setup_service,
            logger=self.logger,
        )

    def setup_service(self) -> Any:
        """Sets up the service for the spreadsheet."""
        provider = service_account_provider("client_secret.json")
        return provider()

    @property
    def service(self) -> Any:
        return self._client._service

    @service.setter
    def service(self, value: Any) -> None:
        self._client._service = value

    def _ensure_service(self) -> None:
        self._client.service

    def find_sheet_id(self, title: str, *, partial: bool = False) -> int | None:
        """Find the spreadsheet ID based on title."""
        return self._client.find_sheet_id(title, partial=partial)

    def write_values_to_sheet_range(
        self, values: list[list[Any]], cell_range: str
    ) -> None:
        """Write a set of values to a column in a spreadsheet."""
        self._client.write_values(values, cell_range, value_input_option="USER_ENTERED")

    def clear_sheet_range(self, cell_range: str) -> None:
        """Clears (values only) a given cell_range."""
        self._client.clear_range(cell_range)

    # def get_values_from_self_range(self):
    #     result = (
    #         self.service.spreadsheets()
    #         .values()
    #         .get(spreadsheetId=self.spreadsheet_id, range=self.cell_range)
    #         .execute()
    #     )
    #     return result.get("values", [])

    def get_values_from_range(self, cell_range: str) -> list[list[Any]]:
        """Fetch values from a given sheet range."""
        return self._client.get_values(cell_range)

    # def sheet_letter_to_index(self, letter):
    #     """1-indexed"""
    #     return ord(letter.lower()) - 96

    # def header_index_to_letter(self, header):
    #     """1-indexed"""
    #     return chr(self.columns.index(header) + 97).upper()


class DFSSheet(Sheet):
    """Methods and ranges specific to my "DFS" sheet object."""

    def __init__(self, sport: str) -> None:
        self.sport = sport

        # set ranges based on sport
        self.start_col = "A"
        if "PGA" in self.sport or self.sport == "GOLF":
            self.end_col = "E"
        else:
            self.end_col = "H"
        self.data_range = "{0}!{1}2:{2}".format(
            self.sport, self.start_col, self.end_col
        )

        self.columns: list[str] | None = None
        self.values: list[list[Any]] | None = None

        # init Sheet (super) class
        super().__init__()

        # if self.values:
        #     self.max_rows = len(self.values)
        #     self.max_columns = len(self.values[0])
        # else:
        #     raise f"No values from self.get_values_from_range({self.cell_range})"

    def clear_standings(self) -> None:
        """Clear standings range of DFSsheet."""
        self.clear_sheet_range(f"{self.data_range}")

    def clear_lineups(self) -> None:
        """Clear lineups range of DFSsheet."""
        lineups_range = self._resolve_lineup_range(new=True)
        self.clear_sheet_range(f"{self.sport}!{lineups_range}")

    def write_players(self, values: list[list[Any]]) -> None:
        """Write players (from standings) to DFSsheet."""
        cell_range = f"{self.data_range}"
        self.write_values_to_sheet_range(values, cell_range)

    def write_column(
        self, column: str, values: list[list[Any]], start_row: int = 2
    ) -> None:
        """Write a set of values to a column in a spreadsheet."""
        # set range based on column e.g. PGAMain!I2:I
        cell_range = f"{self.sport}!{column}{start_row}:{column}"
        self.write_values_to_sheet_range(values, cell_range)

    def write_columns(
        self,
        start_col: str,
        end_col: str,
        values: list[list[Any]],
        start_row: int = 2,
    ) -> None:
        """Write a set of values to columns in a spreadsheet."""
        # set range based on column e.g. PGAMain!I2:I
        cell_range = f"{self.sport}!{start_col}{start_row}:{end_col}"
        self.write_values_to_sheet_range(values, cell_range)

    def write_lineup_range(self, values: list[list[Any]]) -> None:
        """Write values to the configured lineup range."""
        cell_range = f"{self.sport}!{self._resolve_lineup_range(new=False)}"
        self.write_values_to_sheet_range(values, cell_range)

    def add_last_updated(self, dt_updated: datetime) -> None:
        """Update timestamp for sheet."""
        cell_range = f"{self.sport}!L1:Q1"
        values = [["Last Updated", "", dt_updated.strftime("%Y-%m-%d %H:%M:%S")]]
        self.write_values_to_sheet_range(values, cell_range)

    def add_contest_details(
        self, contest_name: str, positions_paid: int | None
    ) -> None:
        """Update timestamp for sheet."""
        cell_range = f"{self.sport}!X1:Y1"
        values = [[positions_paid, contest_name]]
        self.write_values_to_sheet_range(values, cell_range)

    def add_min_cash(self, min_cash: int | float) -> None:
        cell_range = f"{self.sport}!W1:W1"
        values = [[min_cash]]
        self.write_values_to_sheet_range(values, cell_range)

    def add_non_cashing_info(self, non_cashing_info: list[list[Any]]) -> None:
        cell_range = f"{self.sport}!X3:Y16"
        values = non_cashing_info
        self.write_values_to_sheet_range(values, cell_range)

    def add_train_info(self, train_info: list[list[Any]]) -> None:
        cell_range = f"{self.sport}!AA4:AM11"
        values = train_info
        self.write_values_to_sheet_range(values, cell_range)

    def add_optimal_lineup(self, optimal_lineup_info: list[list[Any]]) -> None:
        values = optimal_lineup_info
        cell_range = f"{self.sport}!X25:AC35"
        self.write_values_to_sheet_range(values, cell_range)

    def build_values_for_vip_lineup(self, vip) -> list[list[Any]]:
        if "GOLF" in self.sport:
            values = [[vip.name, None, "PMR", vip.pmr, None, None, None]]
            values.append(["Name", "Salary", "Pts", "Value", "Own", "Pos", "Score"])
            for player in vip.lineup:
                values.append(
                    [
                        player.name,
                        player.salary,
                        player.fpts,
                        player.value,
                        player.ownership,
                        None,
                        None,
                    ]
                )
            values.append(["rank", vip.rank, vip.pts, None, None, None, None])
        else:
            values = [[vip.name, None, "PMR", vip.pmr, None, None]]
            values.append(["Pos", "Name", "Salary", "Pts", "Value", "Own"])
            for player in vip.lineup:
                values.append(
                    [
                        player.pos,
                        player.name,
                        player.salary,
                        player.fpts,
                        player.value,
                        player.ownership,
                    ]
                )
            values.append(["rank", vip.rank, None, vip.pts, None, None])
        return values

    def write_vip_lineups(self, vips: list) -> None:
        cell_range = self._resolve_lineup_range(new=False)
        lineup_mod = 5
        # sort VIPs based on name
        vips.sort(key=lambda x: x.name.lower())
        # add size of lineup + 3 for extra rows
        sport_mod = len(vips[0].lineup) + 3
        all_lineup_values = []
        for i, vip in enumerate(vips):
            values = self.build_values_for_vip_lineup(vip)
            # determine if we have to split list horizontally
            if i < lineup_mod:
                all_lineup_values.extend(values)
            elif i >= lineup_mod:
                for j, k in enumerate(values):
                    mod = (i % lineup_mod) + ((i % lineup_mod) * sport_mod) + j
                    all_lineup_values[mod].extend([""] + k)

            # add extra row to values for spacing if needed
            if i != lineup_mod:
                all_lineup_values.append([])
        self.write_values_to_sheet_range(
            all_lineup_values, f"{self.sport}!{cell_range}"
        )

    def build_values_for_new_vip_lineup(
        self, user: dict[str, Any], players: list[dict[str, Any]]
    ) -> list[list[Any]]:
        values = [[user["user"], None, "PMR", user["pmr"], None, None, None, None]]
        values.append(
            ["Pos", "Name", "Own", "Salary", "Pts", "Value", "RT Proj", "Time", "Stats"]
        )
        for player in players:
            name = player.get("name", "") or ""
            value_icon = player.get("valueIcon")
            if value_icon == "fire":
                name += " 🔥"
            elif value_icon == "ice":
                name += " ❄️"
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
        return values

    def write_new_vip_lineups(self, vip_lineups: list[dict[str, Any]]) -> None:
        cell_range = self._resolve_lineup_range(new=True)

        # sort VIPs based on name
        vip_lineups.sort(key=lambda x: x["user"].lower())
        all_lineup_values = []
        for vip_lineup in vip_lineups:
            values = self.build_values_for_new_vip_lineup(
                vip_lineup, vip_lineup["players"]
            )
            values.append([])
            all_lineup_values.extend(values)

        self.write_values_to_sheet_range(
            all_lineup_values, f"{self.sport}!{cell_range}"
        )

    def get_players(self) -> list[str]:
        self._ensure_loaded()
        assert self.columns is not None
        assert self.values is not None
        return [row[self.columns.index("Name")] for row in self.values]

    def get_lineup_values(self) -> list[list[Any]]:
        return self.get_values_from_range(
            "{0}!{1}".format(self.sport, self._resolve_lineup_range(new=False))
        )

    def _resolve_lineup_range(self, *, new: bool) -> str:
        if new:
            cell_range = get_new_lineup_range(self.sport)
        else:
            cell_range = get_lineup_range(self.sport)
        if not cell_range:
            raise KeyError(f"Missing lineup range for sport '{self.sport}'")
        return cell_range

    def _ensure_loaded(self) -> None:
        if self.columns is None:
            self.columns = self.get_values_from_range(
                "{0}!{1}1:{2}1".format(self.sport, self.start_col, self.end_col)
            )[0]
        if self.values is None:
            self.values = self.get_values_from_range(self.data_range)


def fetch_sheet_gids(spreadsheet_id: str) -> dict[str, int]:
    """Return a mapping of sheet title -> gid for the given spreadsheet."""
    sheet = Sheet()
    service = sheet.setup_service()
    return get_sheet_gids(service, spreadsheet_id)
