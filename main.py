import argparse
import logging
import logging.config
from datetime import datetime
from pytz import timezone

from classes.dfssheet import DFSSheet
from classes.results import Results

# load the logging configuration
logging.config.fileConfig("logging.ini")

"""Use contest ID to update Google Sheet with DFS results.

Example export CSV/ZIP link
https://www.draftkings.com/contest/exportfullstandingscsv/62753724

Example salary CSV link
https://www.draftkings.com/lineup/getavailableplayerscsv?contestTypeId=70&draftGroupId=22401
12 = MLB 21 = NFL 9 = PGA 24 = NASCAR 10 = Soccer 13 = MMA
"""


def main():
    # parse arguments
    parser = argparse.ArgumentParser()
    choices = ["NBA", "NFL", "CFB", "PGAMain", "PGAWeekend", "PGAShowdown", "NHL", "MLB", "TEN"]
    parser.add_argument("-i", "--id", type=int, required=True, help="Contest ID from DraftKings")
    parser.add_argument("-c", "--csv", help="Slate CSV from DraftKings")
    parser.add_argument(
        "-s",
        "--sport",
        choices=choices,
        required=True,
        help="Type of contest (NBA, NFL, PGAMain, PGAWeekend, PGAShowdown, CFB, NHL, or MLB)",
    )
    parser.add_argument("-v", "--verbose", help="Increase verbosity")
    args = parser.parse_args()

    now = datetime.now(timezone("US/Eastern"))

    sheet = DFSSheet(args.sport)

    r = Results(args.sport, args.id, args.csv)
    z = r.players_to_values()
    sheet.write_players(z)
    sheet.add_last_updated(now)

    if r.vip_list:
        sheet.write_vip_lineups(r.vip_list)

    for u in r.vip_list:
        # logger.info("User: {}".format(u.name))
        logger.info("User: {}".format(u))
        # logger.info("Lineup:")
        # for p in u.lineup:
        #     logger.debug(p)

    # sheet = DFSsheet("TEN")


if __name__ == "__main__":
    logger = logging.getLogger(__name__)
    main()
