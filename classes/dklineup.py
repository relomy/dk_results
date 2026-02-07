import argparse
from typing import Any

import yaml

import contests_state
from classes.contestdatabase import ContestDatabase
from classes.dfssheet import DFSSheet
from classes.dksession import DkSession
from classes.sport import Sport


class DkLineup:
    """Fetch VIP lineups for a contest and write them to a sheet."""

    def __init__(self, dksession: DkSession, dk_id: int, draft_group: int) -> None:
        self.dksession = dksession
        self.dk_id = dk_id
        self.draft_group = draft_group

        try:
            # Load the YAML file
            with open("vips.yaml", "r") as file:
                self.vips = yaml.safe_load(file)
        except FileNotFoundError:
            # Handle the case where the file doesn't exist
            self.vips = []
        except yaml.YAMLError as e:
            # Handle YAML parsing errors
            raise ValueError(f"Error parsing YAML file: {e}")
        except Exception as e:
            # Handle other exceptions as needed
            raise e

    def get_leaderboard(self) -> list[dict[str, Any]]:
        """Return leaderboard entries for the configured contest."""
        response = self.dksession.session.get(
            f"https://api.draftkings.com/scores/v1/leaderboards/{self.dk_id}?format=json&embed=leaderboard"
        )
        return response.json()["leaderBoard"]

    def get_vip_users(
        self, leaderboard: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Filter leaderboard entries to VIP users from vips.yaml."""
        for user in leaderboard:
            if user["userName"] in self.vips:
                print()

        found_users = [user for user in leaderboard if user["userName"] in self.vips]
        return found_users

    def get_scorecard_for_user(self, entryKey: int) -> dict[str, Any]:
        """Fetch a scorecard for a leaderboard entry key."""
        response = self.dksession.session.get(
            f"https://api.draftkings.com/scores/v2/entries/{self.draft_group}/{entryKey}?format=json&embed=roster"
        )
        return response.json()

    def get_lineups(self) -> list[dict[str, Any]]:
        """Return VIP lineup payloads suitable for writing to a sheet."""
        leaderboard = self.get_leaderboard()
        vip_users = self.get_vip_users(leaderboard)

        vip_lineups: list[dict[str, Any]] = []
        for user in vip_users:
            scorecard = self.get_scorecard_for_user(user["entryKey"])
            userData = scorecard["entries"][0]
            data = {
                "user": user["userName"],
                "pmr": userData["timeRemaining"],
                "pts": userData["fantasyPoints"],
                "rank": userData["rank"],
            }
            roster = userData["roster"]

            players: list[dict[str, Any]] = []
            default_player = {
                "pos": "",
                "name": "LOCKED 🔒",
                "pts": 0.0,
                "stats": "",
                "ownership": "",
                "pregameProj": 0.0,
                "rtProj": 0.0,
                "timeStatus": "",
                "valueIcon": "",
                "salary": "",
                "value": "",
            }
            for scorecard in roster["scorecards"]:
                d = default_player.copy()
                if "displayName" in scorecard:
                    projection = scorecard["projection"]

                    d["pos"] = scorecard["rosterPosition"]
                    d["name"] = scorecard["displayName"]
                    d["pts"] = scorecard["score"]
                    d["stats"] = scorecard["statsDescription"]
                    d["ownership"] = scorecard["percentDrafted"] / 100
                    rt_proj_raw = projection.get("realTimeProjection", "")
                    if rt_proj_raw not in (None, ""):
                        try:
                            d["rtProj"] = f"{float(rt_proj_raw):.2f}"
                        except (TypeError, ValueError):
                            d["rtProj"] = rt_proj_raw
                    else:
                        d["rtProj"] = ""
                    d["pregameProj"] = projection.get("pregameProjection", "")
                    d["timeStatus"] = scorecard["competition"]["timeStatus"]
                    d["valueIcon"] = scorecard["projection"]["valueIcon"]
                    salary_raw = scorecard.get("salary")
                    salary_val = None
                    if salary_raw not in (None, ""):
                        try:
                            salary_val = int(float(salary_raw))
                            d["salary"] = salary_val
                        except (TypeError, ValueError):
                            salary_val = None

                    pts_raw = scorecard.get("score")
                    if salary_val is not None:
                        try:
                            pts_val = float(pts_raw)
                            if pts_val:
                                # d["value"] = f"{salary_val / pts_val:.2f}"
                                d["value"] = f"{pts_val / (salary_val / 1000):.2f}"
                        except (TypeError, ValueError, ZeroDivisionError):
                            d["value"] = ""
                players.append(d)

            data["players"] = players
            vip_lineups.append(data)

        return vip_lineups


if __name__ == "__main__":
    parser = argparse.ArgumentParser()

    sportz = Sport.__subclasses__()
    choices = dict({sport.name: sport for sport in sportz})

    parser.add_argument(
        "-s",
        "--sport",
        choices=choices,
        required=True,
        help="Type of contest",
        nargs="+",
    )

    contest_database = ContestDatabase(str(contests_state.contests_db_path()))

    args = parser.parse_args()

    for sport_name in args.sport:
        # find matching Sport subclass
        if sport_name not in choices:
            # fail if we don't find one
            raise Exception("Could not find matching Sport subclass")

        sport_obj = choices[sport_name]

        live_contest = contest_database.get_live_contest(
            sport_obj.name, sport_obj.sheet_min_entry_fee, sport_obj.keyword
        )

        if not live_contest:
            continue

        dk_id, name, draft_group, positions_paid, start_date = live_contest

        dksession = DkSession()
        dkl = DkLineup(dksession, dk_id, draft_group)
        lineups = dkl.get_lineups()

        sheet = DFSSheet(sport_name)
        sheet.write_new_vip_lineups(lineups)
