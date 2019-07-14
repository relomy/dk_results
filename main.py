import argparse
import datetime
import logging
import logging.config

from classes.results import Results

# load the logging configuration
logging.config.fileConfig("logging.ini")


def get_args():
    """return arguments for main
    
    Returns:
        args -- argparse
    """
    # parse arguments
    parser = argparse.ArgumentParser()
    choices = [
        "NBA",
        "NFL",
        "CFB",
        "PGAMain",
        "PGAWeekend",
        "PGAShowdown",
        "NHL",
        "MLB",
        "TEN",
    ]
    parser.add_argument(
        "-i", "--id", type=int, required=True, help="Contest ID from DraftKings"
    )
    parser.add_argument("-c", "--csv", help="Slate CSV from DraftKings")
    parser.add_argument(
        "-s",
        "--sport",
        choices=choices,
        required=True,
        help="Type of contest (NBA, NFL, PGA, CFB, NHL, or MLB)",
    )
    parser.add_argument("-v", "--verbose", help="Increase verbosity")
    args = parser.parse_args()
    return args


def main():
    """Use contest ID to update Google Sheet with DFS results.

    Example export CSV/ZIP link
    https://www.draftkings.com/contest/exportfullstandingscsv/62753724

    Example salary CSV link
    https://www.draftkings.com/lineup/getavailableplayerscsv?contestTypeId=70&draftGroupId=22401
    12 = MLB 21 = NFL 9 = PGA 24 = NASCAR 10 = Soccer 13 = MMA
    """

    logger = logging.getLogger(__name__)

    # parse arguments
    args = get_args()

    r = Results(args.sport, args.id, args.csv)

    for u in r.vip_list:
        # logger.info("User: {}".format(u.name))
        logger.info("User: {}".format(u))
        logger.info("Lineup:")
        for p in u.lineup:
            logger.debug(p)


if __name__ == "__main__":
    main()

