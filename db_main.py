import argparse
import csv
import datetime
import io
import logging
import logging.config
import os
import pickle
import zipfile
from collections import OrderedDict

from pytz import timezone

from classes.contestdatabase import ContestDatabase
from classes.dfssheet import DFSSheet
from classes.dksession import DkSession
from classes.draftkings import Draftkings
from classes.optimizer import Optimizer
from classes.results import Results
from classes.sport import Sport
from classes.trainfinder import TrainFinder

# load the logging configuration
logging.config.fileConfig("logging.ini")

logger = logging.getLogger(__name__)


def pull_contest_zip(contest_id):
    """Pull contest file (so far can be .zip or .csv file)."""
    dksession = DkSession()
    session = dksession.get_session()
    return request_contest_url(session, contest_id)


def request_contest_url(session, contest_id):
    contest_dir = "contests"
    fn = os.path.join(contest_dir, f"contest-standings-{contest_id}.csv")

    # attempt to GET contest_csv_url
    url_contest_csv = (
        f"https://www.draftkings.com/contest/exportfullstandingscsv/{contest_id}"
    )
    response = session.get(url_contest_csv)
    logger.debug(response.status_code)
    logger.debug(response.url)
    logger.debug(response.headers["Content-Type"])

    if "text/html" in response.headers["Content-Type"]:
        logger.warning("We cannot do anything with html!")
        return None

    # if headers say file is a CSV file
    if response.headers["Content-Type"] == "text/csv":
        # write working cookies
        with open("pickled_cookies_works.txt", "wb") as fp:
            pickle.dump(session.cookies, fp)
        # decode bytes into string
        csvfile = response.content.decode("utf-8-sig")
        return list(csv.reader(csvfile.splitlines(), delimiter=","))

    zip_obj = zipfile.ZipFile(io.BytesIO(response.content))
    for name in zip_obj.namelist():
        # extract file - it seems easier this way
        path = zip_obj.extract(name, contest_dir)
        logger.debug("path: %s", path)
        with zip_obj.open(name) as csvfile:
            logger.debug("name within zipfile: %s", name)
            # convert to TextIOWrapper object
            lines = io.TextIOWrapper(csvfile, encoding="utf-8", newline="\n")
            # open reader object on csvfile within zip file
            return list(csv.reader(lines, delimiter=","))


def main():
    """Use database and update Google Sheet with contest standings from DraftKings."""
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
    parser.add_argument(
        "--nolineups",
        dest="nolineups",
        action="store_false",
        help="If true, will not print VIP lineups",
    )
    parser.add_argument("-v", "--verbose", help="Increase verbosity")

    args = parser.parse_args()

    # create connection to database file
    contest_database = ContestDatabase("contests.db")

    now = datetime.datetime.now(timezone("US/Eastern"))

    for sport_name in args.sport:
        # find matching Sport subclass
        if sport_name not in choices:
            # fail if we don't find one
            raise Exception("Could not find matching Sport subclass")

        sport_obj = choices[sport_name]

        result = contest_database.get_live_contest(
            sport_obj.name, sport_obj.sheet_min_entry_fee, sport_obj.keyword
        )

        if not result:
            logger.warning("There are no live contests for %s! Moving on.", sport_name)
            continue

        # store dk_id and draft_group from database result
        dk_id, name, draft_group, positions_paid = result

        salary_dir = "salary"
        fn = os.path.join(salary_dir, f"DKSalaries_{sport_name}_{now:%A}.csv")

        logger.debug(args)

        dk = Draftkings()

        if draft_group:
            logger.info("Downloading salary file (draft_group: %d)", draft_group)
            dk.download_salary_csv(sport_name, draft_group, fn)

        # pull contest standings from draftkings
        contest_list = pull_contest_zip(dk_id)

        if contest_list is None or not contest_list:
            logger.error("pull_contest_zip() - contest_list is %s", contest_list)
            continue

        sheet = DFSSheet(sport_name)

        logger.debug(
            "Creating Results object Results(%s, %s, %s)", sport_name, dk_id, fn
        )

        results = Results(sport_obj, dk_id, fn, positions_paid)

        try:
            p = results.get_players()
            optimizer = Optimizer(sport_obj, p)
            optimized_players = optimizer.get_optimal_lineup()

            optimized_players.sort(
                key=lambda x: (sport_obj.positions.index(x.pos), x.name)
            )

            if optimized_players:
                optimized_info = [
                    ["Pos", "Name", "Salary", "Pts", "Value", "Own%"],
                ]
                for player in optimized_players:
                    row = [
                        player.pos,
                        player.name,
                        player.salary,
                        player.fpts,
                        player.value,
                        player.ownership,
                    ]

                    logger.info(
                        f"Player [{player.pos}]: {player.name} Score: {player.fpts} Salary: {player.salary} Value {player.value} Own: {player.ownership}"
                    )

                    optimized_info.append(row)

                sheet.add_optimal_lineup(optimized_info)

                logger.debug(optimized_players)
        except Exception as error:
            logger.error(error)
            logger.error("Error in optimal lineup")

        players_to_values = results.players_to_values(sport_name)
        sheet.clear_standings()
        sheet.write_players(players_to_values)
        sheet.add_contest_details(name, positions_paid)
        logger.info("Writing players to sheet")
        sheet.add_last_updated(now)

        if results.min_cash_pts > 0:
            logger.info("Writing min_cash_pts: %d", results.min_cash_pts)
            sheet.add_min_cash(results.min_cash_pts)

        if args.nolineups and results.vip_list:
            logger.info("Writing vip_lineups to sheet")
            sheet.clear_lineups()
            sheet.write_vip_lineups(results.vip_list)

        if results.non_cashing_users > 0:
            logger.info("Writing non_cashing info")
            info = [
                ["Non-Cashing Info", ""],
                ["Users not cashing", results.non_cashing_users],
                ["Avg PMR Remaining", results.non_cashing_avg_pmr],
            ]

            if results.non_cashing_players:
                info.append(["Top 10 Own% Remaining", ""])
                # sort player dict by how many times they've been seen in non-cashing lineups
                sorted_non_cashing_players = {
                    k: v
                    for k, v in sorted(
                        results.non_cashing_players.items(),
                        key=lambda item: item[1],
                        reverse=True,
                    )
                }
                # take top 10
                top_ten_players = list(sorted_non_cashing_players)[:10]
                for p in top_ten_players:
                    count = results.non_cashing_players[p]
                    ownership = float(count / results.non_cashing_users)
                    info.append([p, ownership])

            sheet.add_non_cashing_info(info)

        if results and results.users:
            trainfinder = TrainFinder(results.users)

            salary_limit = 40000

            logger.info("total users:")
            logger.info(trainfinder.get_total_users())
            logger.info(f"total users above salary ${salary_limit}")
            logger.info(trainfinder.get_total_users_above_salary(salary_limit))
            logger.info(f"total scores above salary ${salary_limit}")

            trains = trainfinder.get_users_above_salary_spent(salary_limit)

            delete_keys = [key for key in trains if trains[key]["count"] == 1]

            for key in delete_keys:
                del trains[key]

            sorted_trains = OrderedDict(
                sorted(trains.items(), key=lambda kv: kv[1]["count"], reverse=True)[:5]
            )

            info = [
                ["Rank", "Users", "Score", "PMR"],
            ]
            for k, v in sorted_trains.items():
                row = [v["rank"], v["count"], v["pts"], v["pmr"]]

                logger.info(
                    f"Users: {v['count']} Score: {v['pts']} PMR: {v['pmr']} Lineup: {v['lineup']}"
                )

                lineupobj = v["lineup"]

                # expand the players, in order per sport, from the lineup
                if lineupobj:
                    row.extend([player.name for player in lineupobj.lineup])

                info.append(row)

            sheet.add_train_info(info)


if __name__ == "__main__":
    main()
