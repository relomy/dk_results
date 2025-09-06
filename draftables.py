import logging
import logging.config

import requests

from classes.dksession import DkSession

# load the logging configuration
logging.config.fileConfig("logging.ini")
logger = logging.getLogger(__name__)


dksession = DkSession()
session = dksession.get_session()

dk_id = 153835936
dg = 95447

response = requests.get(
    f"https://api.draftkings.com/draftgroups/v1/draftgroups/{dg}/draftables/"
)

js = response.json()

draftables = js["draftables"]
competitions = js["competitions"]
draftStats = js["draftStats"]
playerGameAttributes = js["playerGameAttributes"]

draftable = draftables[0]

leaderboard_response = session.get(
    f"https://api.draftkings.com/scores/v1/leaderboards/{dk_id}?format=json&embed=leaderboard"
)

js_leaderboard = leaderboard_response.json()

vips = [
    "aplewandowski",
    "FlyntCoal",
    "Cubbiesftw23",
    "Mcoleman1902",
    "cglenn91",
    "tuck8989",
    "Notorious",
    "Bra3105",
    "ChipotleAddict",
    "papagates",
    "EmpireMaker2",
    "AdamLevitan",
]

found_users = [
    user for user in js_leaderboard["leaderBoard"] if user["userName"] in vips
]

for user in found_users:
    print(user["userName"])
    entryKey = user["entryKey"]
    scorecard_response = session.get(
        f"https://api.draftkings.com/scores/v2/entries/{dg}/{entryKey}?format=json&embed=roster"
    )
    scorecard_js = scorecard_response.json()

    roster = scorecard_js["entries"][0]["roster"]

    for scorecard in roster["scorecards"]:
        if "shortName" in scorecard:
            print(
                f"    shortName: {scorecard['shortName']} statsDescription: {scorecard['statsDescription']}"
            )
            print(scorecard)
        else:
            print(scorecard)
