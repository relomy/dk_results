import logging
import logging.config
import os

from google.oauth2 import service_account
from googleapiclient.discovery import build

from .sport import get_lineup_range, get_new_lineup_range
logging.config.fileConfig("logging.ini")


class Sheet:
    """Object to represent Google Sheet."""

    def __init__(self, logger=None):
        self.logger = logger or logging.getLogger(__name__)

        # unique ID for DFS Ownership/Value spreadsheet
        self.spreadsheet_id = os.getenv("SPREADSHEET_ID")
        self.service = None

    def setup_service(self):
        """Sets up the service for the spreadsheet."""
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]
        directory = "."
        secret_file = os.path.join(directory, "client_secret.json")

        credentials = service_account.Credentials.from_service_account_file(
            secret_file, scopes=scopes
        )

        return build("sheets", "v4", credentials=credentials, cache_discovery=False)

    def _ensure_service(self):
        if self.service is None:
            self.service = self.setup_service()

    def find_sheet_id(self, title):
        """Find the spreadsheet ID based on title."""
        self._ensure_service()
        sheet_metadata = (
            self.service.spreadsheets().get(spreadsheetId=self.spreadsheet_id).execute()
        )
        sheets = sheet_metadata.get("sheets", "")
        for sheet in sheets:
            if title in sheet["properties"]["title"]:
                # logger.debug("Sheet ID for %s is %s", title, sheet["properties"]["sheetId"])
                return sheet["properties"]["sheetId"]

        return None

    def write_values_to_sheet_range(self, values, cell_range):
        """Write a set of values to a column in a spreadsheet."""
        self._ensure_service()
        body = {"values": values}
        value_input_option = "USER_ENTERED"
        result = (
            self.service.spreadsheets()
            .values()
            .update(
                spreadsheetId=self.spreadsheet_id,
                range=cell_range,
                valueInputOption=value_input_option,
                body=body,
            )
            .execute()
        )
        self.logger.info(
            "%s cells updated for [%s].", cell_range, result.get("updatedCells")
        )

    def clear_sheet_range(self, cell_range):
        """Clears (values only) a given cell_range."""
        self._ensure_service()
        result = (
            self.service.spreadsheets()
            .values()
            .clear(
                spreadsheetId=self.spreadsheet_id,
                range=cell_range,
                body={},  # must be empty
            )
            .execute()
        )
        self.logger.info("Range %s cleared.", result.get("clearedRange"))

    # def get_values_from_self_range(self):
    #     result = (
    #         self.service.spreadsheets()
    #         .values()
    #         .get(spreadsheetId=self.spreadsheet_id, range=self.cell_range)
    #         .execute()
    #     )
    #     return result.get("values", [])

    def get_values_from_range(self, cell_range):
        self._ensure_service()
        result = (
            self.service.spreadsheets()
            .values()
            .get(spreadsheetId=self.spreadsheet_id, range=cell_range)
            .execute()
        )
        return result.get("values", [])

    # def sheet_letter_to_index(self, letter):
    #     """1-indexed"""
    #     return ord(letter.lower()) - 96

    # def header_index_to_letter(self, header):
    #     """1-indexed"""
    #     return chr(self.columns.index(header) + 97).upper()


class DFSSheet(Sheet):
    """Methods and ranges specific to my "DFS" sheet object."""

    def __init__(self, sport):
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

        self.columns = None
        self.values = None

        # init Sheet (super) class
        super().__init__()

        # if self.values:
        #     self.max_rows = len(self.values)
        #     self.max_columns = len(self.values[0])
        # else:
        #     raise f"No values from self.get_values_from_range({self.cell_range})"

    def clear_standings(self):
        """Clear standings range of DFSsheet."""
        self.clear_sheet_range(f"{self.data_range}")

    def clear_lineups(self):
        """Clear lineups range of DFSsheet."""
        lineups_range = self._resolve_lineup_range(new=True)
        self.clear_sheet_range(f"{self.sport}!{lineups_range}")

    def write_players(self, values):
        """Write players (from standings) to DFSsheet."""
        cell_range = f"{self.data_range}"
        self.write_values_to_sheet_range(values, cell_range)

    def write_column(self, column, values, start_row=2):
        """Write a set of values to a column in a spreadsheet."""
        # set range based on column e.g. PGAMain!I2:I
        cell_range = f"{self.sport}!{column}{start_row}:{column}"
        self.write_values_to_sheet_range(values, cell_range)

    def write_columns(self, start_col, end_col, values, start_row=2):
        """Write a set of values to columns in a spreadsheet."""
        # set range based on column e.g. PGAMain!I2:I
        cell_range = f"{self.sport}!{start_col}{start_row}:{end_col}"
        self.write_values_to_sheet_range(values, cell_range)

    def write_lineup_range(self, values):
        cell_range = f"{self.sport}!{self._resolve_lineup_range(new=False)}"
        self.write_values_to_sheet_range(values, cell_range)

    def add_last_updated(self, dt_updated):
        """Update timestamp for sheet."""
        cell_range = f"{self.sport}!L1:Q1"
        values = [["Last Updated", "", dt_updated.strftime("%Y-%m-%d %H:%M:%S")]]
        self.write_values_to_sheet_range(values, cell_range)

    def add_contest_details(self, contest_name, positions_paid):
        """Update timestamp for sheet."""
        cell_range = f"{self.sport}!X1:Y1"
        values = [[positions_paid, contest_name]]
        self.write_values_to_sheet_range(values, cell_range)

    def add_min_cash(self, min_cash):
        cell_range = f"{self.sport}!W1:W1"
        values = [[min_cash]]
        self.write_values_to_sheet_range(values, cell_range)

    def add_non_cashing_info(self, non_cashing_info):
        cell_range = f"{self.sport}!X3:Y16"
        values = non_cashing_info
        self.write_values_to_sheet_range(values, cell_range)

    def add_train_info(self, train_info):
        cell_range = f"{self.sport}!AA4:AM11"
        values = train_info
        self.write_values_to_sheet_range(values, cell_range)

    def add_optimal_lineup(self, optimal_lineup_info):
        values = optimal_lineup_info
        cell_range = f"{self.sport}!X25:AC35"
        self.write_values_to_sheet_range(values, cell_range)

    def build_values_for_vip_lineup(self, vip):
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

    def write_vip_lineups(self, vips):
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

    def build_values_for_new_vip_lineup(self, user, players):
        values = [[user["user"], None, "PMR", user["pmr"], None, None, None, None]]
        values.append(["Pos", "Name", "Own", "Pts", "Value", "RT Proj", "Time", "Stats"])
        for d in players:
            name = d.get("name", "") or ""
            value_icon = d.get("valueIcon")
            if value_icon == "fire":
                name += " 🔥"
            elif value_icon == "ice":
                name += " ❄️"
            values.append(
                [
                    d.get("pos", ""),
                    name,
                    d.get("ownership", ""),
                    d.get("pts", ""),
                    d.get("value", ""),
                    d.get("rtProj", ""),
                    d.get("timeStatus", ""),
                    d.get("stats", ""),
                ]
            )
        values.append(["rank", user["rank"], None, user["pts"], None, None, None, None])
        return values

    def write_new_vip_lineups(self, vip_lineups):
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

    def get_players(self):
        self._ensure_loaded()
        return [row[self.columns.index("Name")] for row in self.values]

    def get_lineup_values(self):
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

    def _ensure_loaded(self):
        if self.columns is None:
            self.columns = self.get_values_from_range(
                "{0}!{1}1:{2}1".format(self.sport, self.start_col, self.end_col)
            )[0]
        if self.values is None:
            self.values = self.get_values_from_range(self.data_range)
