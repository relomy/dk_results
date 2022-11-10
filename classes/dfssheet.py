import logging
import logging.config
from os import path

from google.oauth2 import service_account
from googleapiclient.discovery import build
from httplib2 import Http

logging.config.fileConfig("logging.ini")


class Sheet:
    """Object to represent Google Sheet."""

    def __init__(self, logger=None):
        self.logger = logger or logging.getLogger(__name__)

        # authorize class to use sheets API
        self.service = self.setup_service()

        # unique ID for DFS Ownership/Value spreadsheet
        self.spreadsheet_id = "1Jv5nT-yUoEarkzY5wa7RW0_y0Dqoj8_zDrjeDs-pHL4"

    def setup_service(self):
        """Sets up the service for the spreadsheet."""
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]
        directory = "."
        secret_file = path.join(directory, "client_secret.json")

        credentials = service_account.Credentials.from_service_account_file(
            secret_file, scopes=scopes
        )

        return build("sheets", "v4", credentials=credentials, cache_discovery=False)

    def find_sheet_id(self, title):
        """Find the spreadsheet ID based on title."""
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

    LINEUP_RANGES = {
        "NBA": "J3:V61",
        "CFB": "J3:V61",
        "NFL": "J3:V66",
        "NFLShowdown": "J3:V66",
        "GOLF": "L8:Z56",
        "PGAMain": "L8:X56",
        "PGAWeekend": "L3:Q41",
        "PGAShowdown": "L3:Q41",
        "TEN": "J3:V61",
        "MLB": "J3:V71",
        "XFL": "J3:V56",
        "MMA": "J3:V61",
        "LOL": "J3:V61",
        "NAS": "J3:V61",
        "USFL": "J3:V66",
    }

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

        # init Sheet (super) class
        super().__init__()

        # get columns from first row
        self.columns = self.get_values_from_range(
            "{0}!{1}1:{2}1".format(self.sport, self.start_col, self.end_col)
        )[0]

        self.values = self.get_values_from_range(self.data_range)

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
        lineups_range = self.LINEUP_RANGES[self.sport]
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
        cell_range = f"{self.sport}!{self.LINEUP_RANGES[self.sport]}"
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
        cell_range = f"{self.sport}!AA3:AM10"
        values = train_info
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
        cell_range = self.LINEUP_RANGES[self.sport]
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

    def get_players(self):
        return [row[self.columns.index("Name")] for row in self.values]

    def get_lineup_values(self):
        return self.get_values_from_range(
            "{0}!{1}".format(self.sport, self.LINEUP_RANGES[self.sport])
        )
