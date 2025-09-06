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

# Centralized constants
CONTEST_DIR = "contests"
SALARY_DIR = "salary"
DB_FILE = "contests.db"
SALARY_LIMIT = 40000
COOKIES_FILE = "pickled_cookies_works.txt"


def pull_contest_zip(contest_id: int) -> list | None:
    """
    Pull contest file (can be .zip or .csv file) from DraftKings.

    Args:
        contest_id (int): Contest ID.

    Returns:
        list | None: List of contest rows or None if not found.
    """
    dksession = DkSession()
    session = dksession.get_session()
    return request_contest_url(session, contest_id)


def request_contest_url(session, contest_id: int) -> list | None:
    """
    Request contest standings file from DraftKings.

    Args:
        session: Authenticated requests session.
        contest_id (int): Contest ID.

    Returns:
        list | None: List of contest rows or None if not found.
    """
    fn = os.path.join(CONTEST_DIR, f"contest-standings-{contest_id}.csv")
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

    if response.headers["Content-Type"] == "text/csv":
        with open(COOKIES_FILE, "wb") as fp:
            pickle.dump(session.cookies, fp)
        csvfile = response.content.decode("utf-8-sig")
        return list(csv.reader(csvfile.splitlines(), delimiter=","))

    zip_obj = zipfile.ZipFile(io.BytesIO(response.content))
    for name in zip_obj.namelist():
        path = zip_obj.extract(name, CONTEST_DIR)
        logger.debug("path: %s", path)
        with zip_obj.open(name) as csvfile:
            logger.debug("name within zipfile: %s", name)
            lines = io.TextIOWrapper(csvfile, encoding="utf-8", newline="\n")
            return list(csv.reader(lines, delimiter=","))


def write_players_to_sheet(
    sheet: DFSSheet, results: Results, sport_name: str, now: datetime.datetime
) -> None:
    """
    Write player values and contest details to the sheet.

    Args:
        sheet (DFSSheet): Sheet object.
        results (Results): Results object.
        sport_name (str): Sport name.
        now (datetime.datetime): Current datetime.
    """
    players_to_values = results.players_to_values(sport_name)
    sheet.clear_standings()
    sheet.write_players(players_to_values)
    sheet.add_contest_details(results.name, results.positions_paid)
    logger.info("Writing players to sheet")
    sheet.add_last_updated(now)
    if results.min_cash_pts > 0:
        logger.info("Writing min_cash_pts: %d", results.min_cash_pts)
        sheet.add_min_cash(results.min_cash_pts)
    if results.vip_list:
        logger.info("Writing vip_lineups to sheet")
        sheet.clear_lineups()
        sheet.write_vip_lineups(results.vip_list)


def write_non_cashing_info(sheet: DFSSheet, results: Results) -> None:
    """
    Write non-cashing user info to the sheet.

    Args:
        sheet (DFSSheet): Sheet object.
        results (Results): Results object.
    """
    if results.non_cashing_users > 0:
        logger.info("Writing non_cashing info")
        info = [
            ["Non-Cashing Info", ""],
            ["Users not cashing", results.non_cashing_users],
            ["Avg PMR Remaining", results.non_cashing_avg_pmr],
        ]
        if results.non_cashing_players:
            info.append(["Top 10 Own% Remaining", ""])
            sorted_non_cashing_players = {
                k: v
                for k, v in sorted(
                    results.non_cashing_players.items(),
                    key=lambda item: item[1],
                    reverse=True,
                )
            }
            top_ten_players = [
                p for p, _ in list(sorted_non_cashing_players.items())[:10]
            ]
            for p in top_ten_players:
                count = results.non_cashing_players[p]
                ownership = float(count / results.non_cashing_users)
                info.append([p, ownership])
        sheet.add_non_cashing_info(info)


def write_train_info(sheet: DFSSheet, results: Results) -> None:
    """
    Write train info to the sheet.

    Args:
        sheet (DFSSheet): Sheet object.
        results (Results): Results object.
    """
    if results and results.users:
        trainfinder = TrainFinder(results.users)
        logger.info("total users:")
        logger.info(trainfinder.get_total_users())
        logger.info(f"total users above salary ${SALARY_LIMIT}")
        logger.info(trainfinder.get_total_users_above_salary(SALARY_LIMIT))
        logger.info(f"total scores above salary ${SALARY_LIMIT}")

        trains = trainfinder.get_users_above_salary_spent(SALARY_LIMIT)
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
            if lineupobj:
                row.extend([player.name for player in lineupobj.lineup])
            info.append(row)
        sheet.add_train_info(info)


def process_sport(
    sport_name: str,
    choices: dict[str, type],
    contest_database: ContestDatabase,
    now: datetime.datetime,
    args: argparse.Namespace,
) -> None:
    """
    Process a single sport: download salary, pull contest, update sheet.

    Args:
        sport_name (str): Name of the sport.
        choices (dict[str, type]): Dictionary mapping sport names to Sport subclasses.
        contest_database (ContestDatabase): Contest database instance.
        now (datetime.datetime): Current datetime.
        args (argparse.Namespace): Parsed command-line arguments.
    """
    if sport_name not in choices:
        raise Exception("Could not find matching Sport subclass")
    sport_obj = choices[sport_name]
    result = contest_database.get_live_contest(
        sport_obj.name, sport_obj.sheet_min_entry_fee, sport_obj.keyword
    )
    if not result:
        logger.warning("There are no live contests for %s! Moving on.", sport_name)
        return

    dk_id, name, draft_group, positions_paid = result
    fn = os.path.join(SALARY_DIR, f"DKSalaries_{sport_name}_{now:%A}.csv")
    logger.debug(args)
    dk = Draftkings()
    if draft_group:
        logger.info("Downloading salary file (draft_group: %d)", draft_group)
        dk.download_salary_csv(sport_name, draft_group, fn)
    contest_list = pull_contest_zip(dk_id)
    if contest_list is None or not contest_list:
        logger.error("pull_contest_zip() - contest_list is %s", contest_list)
        return

    sheet = DFSSheet(sport_name)
    logger.debug("Creating Results object Results(%s, %s, %s)", sport_name, dk_id, fn)
    results = Results(sport_obj, dk_id, fn, positions_paid)
    results.name = name
    results.positions_paid = positions_paid

    try:
        p = results.get_players()
        optimizer = Optimizer(sport_obj, p)
        optimized_players = optimizer.get_optimal_lineup()
        optimized_players.sort(key=lambda x: (sport_obj.positions.index(x.pos), x.name))
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

    write_players_to_sheet(sheet, results, sport_name, now)
    write_non_cashing_info(sheet, results)
    write_train_info(sheet, results)


def main() -> None:
    """
    Use database and update Google Sheet with contest standings from DraftKings.
    """
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
    contest_database = ContestDatabase(DB_FILE)
    now = datetime.datetime.now(timezone("US/Eastern"))
    for sport_name in args.sport:
        process_sport(sport_name, choices, contest_database, now, args)


if __name__ == "__main__":
    main()
