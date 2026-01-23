import argparse
import datetime
import logging
import logging.config
import os
import pathlib
from collections import OrderedDict
from typing import Any

import yaml
from pytz import timezone

from classes.contestdatabase import ContestDatabase
from classes.dfssheet import DFSSheet
from classes.draftkings import Draftkings
from classes.optimizer import Optimizer
from classes.results import Results
from classes.sport import Sport
from classes.trainfinder import TrainFinder

# load the logging configuration
logging.config.fileConfig("logging.ini")

logger = logging.getLogger(__name__)

# typing helpers
SportType = type[Sport]

# Centralized constants
CONTEST_DIR = "contests"
SALARY_DIR = "salary"
DB_FILE = "contests.db"
SALARY_LIMIT = 40000
COOKIES_FILE = "pickled_cookies_works.txt"


def load_vips() -> list[str]:
    """
    Load VIP usernames from vips.yaml located next to this file.
    Returns an empty list if the file is missing or malformed.
    """
    vip_path = pathlib.Path(__file__).parent / "vips.yaml"
    try:
        with open(vip_path, "r") as f:
            vips = yaml.safe_load(f) or []
        if not isinstance(vips, list):
            logger.warning("vips.yaml did not contain a list; treating as empty.")
            return []
        # Normalize to strings and strip whitespace
        return [str(x).strip() for x in vips if str(x).strip()]
    except FileNotFoundError:
        logger.warning(
            "vips.yaml not found at %s; proceeding with empty VIP list.", vip_path
        )
        return []
    except Exception as e:
        logger.warning(
            "Failed to load vips.yaml: %s; proceeding with empty VIP list.", e
        )
        return []


def write_players_to_sheet(
    sheet: DFSSheet,
    results: Results,
    sport_name: str,
    now: datetime.datetime,
    dk: Draftkings,
    draft_group: int | None = None,
) -> None:
    """
    Write player values and contest details to the sheet.

    Args:
        sheet (DFSSheet): Sheet object.
        results (Results): Results object.
        sport_name (str): Sport name.
        now (datetime.datetime): Current datetime.
        dk (Draftkings): Authenticated DraftKings API client.
        draft_group (int, optional): Draft group id.
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

    vips = load_vips()
    dk_id = results.contest_id
    dg = draft_group
    if dg is None:
        logger.warning(
            "No draft group found for sport, cannot pull VIP lineups from API."
        )
        return

    vip_entries: dict[str, dict[str, Any] | str] = {}
    for vip in results.vip_list:
        if not vip.name or not vip.player_id:
            continue
        vip_entries[vip.name] = {
            "entry_key": vip.player_id,
            "pmr": vip.pmr,
            "rank": vip.rank,
            "pts": vip.pts,
        }
    player_salary_map: dict[str, int] = {
        name: player.salary for name, player in results.players.items()
    }
    vip_lineups: list[dict] = dk.get_vip_lineups(
        dk_id,
        dg,
        vips,
        vip_entries=vip_entries,
        player_salary_map=player_salary_map,
    )
    if vip_lineups:
        logger.info("Writing API vip_lineups to sheet")
        sheet.clear_lineups()
        sheet.write_new_vip_lineups(vip_lineups)


def write_non_cashing_info(sheet: DFSSheet, results: Results) -> None:
    """
    Write non-cashing user info to the sheet.

    Args:
        sheet (DFSSheet): Sheet object.
        results (Results): Results object.
    """
    if results.non_cashing_users > 0:
        logger.info("Writing non_cashing info")
        info: list[list[Any]] = [
            ["Non-Cashing Info", ""],
            ["Users not cashing", results.non_cashing_users],
            ["Avg PMR Remaining", results.non_cashing_avg_pmr],
        ]
        if results.non_cashing_players:
            info.append(["Top 10 Own% Remaining", ""])
            sorted_non_cashing_players: dict[str, int] = {
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

        trains: dict[str, dict[str, Any]] = trainfinder.get_users_above_salary_spent(
            SALARY_LIMIT
        )
        delete_keys = [key for key in trains if trains[key]["count"] == 1]
        for key in delete_keys:
            del trains[key]
        sorted_trains: OrderedDict[str, dict[str, Any]] = OrderedDict(
            sorted(trains.items(), key=lambda kv: kv[1]["count"], reverse=True)[:5]
        )
        info: list[list[Any]] = [
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
    choices: dict[str, SportType],
    contest_database: ContestDatabase,
    now: datetime.datetime,
    args: argparse.Namespace,
    vips: list[str],
) -> None:
    """
    Process a single sport: download salary, pull contest, update sheet.

    Args:
        sport_name (str): Name of the sport.
        choices (dict[str, type]): Dictionary mapping sport names to Sport subclasses.
        contest_database (ContestDatabase): Contest database instance.
        now (datetime.datetime): Current datetime.
        args (argparse.Namespace): Parsed command-line arguments.
        vips (list[str]): VIP usernames loaded from vips.yaml.
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

    dk_id, name, draft_group, positions_paid, start_date = result
    fn = os.path.join(SALARY_DIR, f"DKSalaries_{sport_name}_{now:%A}.csv")
    logger.debug(args)
    dk = Draftkings()
    if draft_group:
        logger.info("Downloading salary file (draft_group: %d)", draft_group)
        dk.download_salary_csv(sport_name, draft_group, fn)

    contest_list: list[list[str]] | None = dk.download_contest_rows(
        dk_id, timeout=30, cookies_dump_file=COOKIES_FILE, contest_dir=CONTEST_DIR
    )
    if not contest_list:
        logger.warning(
            "Contest standings download failed or was empty for dk_id=%s; skipping.",
            dk_id,
        )
        return

    sheet = DFSSheet(sport_name)
    logger.debug("Creating Results object Results(%s, %s, %s)", sport_name, dk_id, fn)
    results: Results = Results(
        sport_obj,
        dk_id,
        fn,
        positions_paid,
        standings_rows=contest_list,
        vips=vips,
    )
    results.name = name
    results.positions_paid = positions_paid

    try:
        if (sport_obj.allow_optimizer is False) or (not args.nolineups):
            logger.info("Skipping optimal lineup for %s", sport_name)
        else:
            p = results.get_players()
            optimizer = Optimizer(sport_obj, p)
            optimized_players = optimizer.get_optimal_lineup()
            if optimized_players:
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

    write_players_to_sheet(sheet, results, sport_name, now, dk, draft_group)
    write_non_cashing_info(sheet, results)
    write_train_info(sheet, results)


def main() -> None:
    """
    Use database and update Google Sheet with contest standings from DraftKings.
    """
    parser = argparse.ArgumentParser()
    sportz: list[SportType] = Sport.__subclasses__()
    choices: dict[str, SportType] = {sport.name: sport for sport in sportz}
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
    vips = load_vips()
    now = datetime.datetime.now(timezone("US/Eastern"))
    for sport_name in args.sport:
        process_sport(sport_name, choices, contest_database, now, args, vips)


if __name__ == "__main__":
    main()
