from os import path

from googleapiclient.discovery import build
from httplib2 import Http
from oauth2client import client, file, tools


class Sheet(object):
    def __init__(self):

        # authorize class to use sheets API
        self.service = self.setup_service()

        # unique ID for DFS Ownership/Value spreadsheet
        self.SPREADSHEET_ID = "1Jv5nT-yUoEarkzY5wa7RW0_y0Dqoj8_zDrjeDs-pHL4"

        # self.values = self.get_values_from_range(self.cell_range)

        # if self.values:
        #     self.max_rows = len(self.values)
        #     self.max_columns = len(self.values[0])
        # else:
        #     raise f"No values from self.get_values_from_range({self.cell_range})"

    def setup_service(self):
        SCOPES = "https://www.googleapis.com/auth/spreadsheets"
        dir = "."
        store = file.Storage(path.join(dir, "token.json"))
        creds = store.get()
        if not creds or creds.invalid:
            flow = client.flow_from_clientsecrets(path.join(dir, "token.json"), SCOPES)
            creds = tools.run_flow(flow, store)
        return build("sheets", "v4", http=creds.authorize(Http()), cache_discovery=False)

    def find_sheet_id(self, title):
        sheet_metadata = (
            self.service.spreadsheets().get(spreadsheetId=self.SPREADSHEET_ID).execute()
        )
        sheets = sheet_metadata.get("sheets", "")
        for sheet in sheets:
            if title in sheet["properties"]["title"]:
                # logger.debug("Sheet ID for {} is {}".format(title, sheet["properties"]["sheetId"]))
                return sheet["properties"]["sheetId"]

    def write_values_to_sheet_range(self, values, range):
        """Write a set of values to a column in a spreadsheet."""
        body = {"values": values}
        value_input_option = "USER_ENTERED"
        result = (
            self.service.spreadsheets()
            .values()
            .update(
                spreadsheetId=self.SPREADSHEET_ID,
                range=range,
                valueInputOption=value_input_option,
                body=body,
            )
            .execute()
        )
        print("{0} cells updated.".format(result.get("updatedCells")))

    def get_values_from_self_range(self):
        result = (
            self.service.spreadsheets()
            .values()
            .get(spreadsheetId=self.SPREADSHEET_ID, range=self.cell_range)
            .execute()
        )
        return result.get("values", [])

    def get_values_from_range(self, range):
        result = (
            self.service.spreadsheets()
            .values()
            .get(spreadsheetId=self.SPREADSHEET_ID, range=range)
            .execute()
        )
        return result.get("values", [])

    def sheet_letter_to_index(self, letter):
        """1-indexed"""
        return ord(letter.lower()) - 96

    def header_index_to_letter(self, header):
        """1-indexed"""
        return chr(self.columns.index(header) + 97).upper()


class DFSSheet(Sheet):
    LINEUP_RANGES = {
        "PGA": ["L3:Q11", "L13:Q21", "L23:Q31", "L33:Q41"],
        # "TEN": ["J3:O11", "J13:O21", "J23:O31", "J33:O41"],
        "TEN": "J3:V41",
    }

    def __init__(self, sport, cell_range):
        self.sport = sport
        self.cell_range = cell_range

        super().__init__()

        # self.zzz = self.get_values_from_range(cell_range)

    def write_players(self, values):
        cell_range = f"{self.sport}!{self.cell_range}"
        self.write_values_to_sheet_range(values, cell_range)

    def write_column(self, column, values):
        """Write a set of values to a column in a spreadsheet."""
        # set range based on column e.g. PGAMain!I2:I
        cell_range = f"{self.sport}!{column}2:{column}"
        return super().write_values_to_sheet_range(cell_range, values)

    def build_values_for_vip_lineup(self, vip):
        values = [
            [vip.name, "", "PMR", vip.pmr, "", ""],
            ["Pos", "Name", "Salary", "Pts", "Value", "Own"],
        ]
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
        values.append(["rank", vip.rank, "", vip.pts, "", ""])
        values.append(["", "", "", "", ""])
        return values

    def write_vip_lineups(self, vips):
        cell_range = self.LINEUP_RANGES[self.sport]
        lineup_mod = 2
        sport_mod = 9
        all_lineup_values = []
        for i, vip in enumerate(vips):
            values = self.build_values_for_vip_lineup(vip)
            # determine if we have to split list horizontally
            if i < lineup_mod:
                all_lineup_values.extend(values)
            elif i >= lineup_mod:
                # mod = (i % 4) + ((i % 4) * 10) + j
                for j, z in enumerate(values):
                    mod = (i % lineup_mod) + ((i % lineup_mod) * sport_mod) + j
                    all_lineup_values[mod].extend([""] + z)
            # all_lineup_values.extend(self.build_values_for_vip_lineup(vip))
            # values = []
            # values.append([vip.name, "", "PMR", vip.pmr, "", ""])
            # values.append(["Pos", "Name", "Salary", "Pts", "Value", "Own"])
            # for p in vip.lineup:
            #     values.append([p.pos, p.name, p.salary, p.fpts, p.value, p.ownership])

            # values.append(["rank", vip.rank, "", vip.pts, "", ""])
        self.write_values_to_sheet_range(all_lineup_values, f"{self.sport}!{cell_range}")

    def get_players(self):
        return [row[self.columns.index("Name")] for row in self.values]


# class DFSsheet_TEN(DFSsheet):
#     def __init__(self):
#         # current PGA sheet columns
#         columns = ["Position", "Name", "Team", "Matchup", "Salary", "Ownership", "Points", "Values"]
#         sport = "TEN"
#         cell_range = f"A2:E"

#         # call DFSsheet constructor
#         super().__init__("TEN", cell_range, columns)

#         self.lineups = []

#         lineup_cell_ranges = ["J3:O11", "J13:O21", "J23:O31", "J33:O41"]

#         for cell_range in lineup_cell_ranges:
#             lineup = self.get_lineup(cell_range)
#             if any(lineup):
#                 self.lineups.append(lineup)
#             else:
#                 print("any(lineup) returned false")

#     def get_lineup(self, cell_range):
#         return super().get_values_from_range(cell_range)


# class DFSsheet_PGA(DFSsheet):
#     def __init__(self):
#         # current PGA sheet columns
#         columns = [
#             "Position",
#             "Name",
#             "Team",
#             "Matchup",
#             "Salary",
#             "Ownership",
#             "Points",
#             "Values",
#             "mc",
#         ]

#         DFSsheet.__init__(self, "PGAMain", "A2:I", columns)

