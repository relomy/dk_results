import argparse
import datetime
import logging
import os
import pathlib
import sqlite3
import time
from collections import OrderedDict
from typing import Any
from zoneinfo import ZoneInfo

import yaml
from dfs_common import state
from dfs_common.discord import WebhookSender

from dk_results.classes.bonus_announcements import announce_vip_bonuses
from dk_results.classes.contestdatabase import ContestDatabase
from dk_results.classes.dfs_sheet_service import DfsSheetService
from dk_results.classes.draftkings import Draftkings
from dk_results.classes.optimizer import Optimizer
from dk_results.classes.results import Results
from dk_results.classes.sheets_service import build_dfs_sheet_service
from dk_results.classes.sport import Sport
from dk_results.classes.trainfinder import TrainFinder
from dk_results.config import load_and_apply_settings
from dk_results.logging import configure_logging
from dk_results.paths import repo_file
from dk_results.services.snapshot_exporter import (
    DEFAULT_STANDINGS_LIMIT,
    build_snapshot,
    normalize_snapshot_for_output,
    to_stable_json,
    to_utc_iso,
)

logger = logging.getLogger(__name__)

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover

    def load_dotenv(*_args, **_kwargs):
        return False


# typing helpers
SportType = type[Sport]

# Centralized constants
CONTEST_DIR = str(repo_file("contests"))
SALARY_DIR = str(repo_file("salary"))
SALARY_LIMIT = 40000
COOKIES_FILE = str(repo_file("pickled_cookies_works.txt"))
LEGACY_VIP_EVENT_COMPAT_ENV = "DK_VIP_EVENT_COMPAT"
LEGACY_VIP_EVENT_REMOVE_AFTER = "2026-04-30"
LEGACY_VIP_EVENT_MAP = {
    "vip_detection": "vip_detection_summary",
    "vip_fetch": "vip_lineups_fetch",
    "vip_sheet_write": "vip_lineups_summary",
}


def _format_log_value(value: Any) -> str:
    if isinstance(value, bool):
        return str(value).lower()
    if value is None:
        return "none"
    return str(value)


def _format_event_fields(fields: dict[str, Any]) -> str:
    return " ".join(f"{key}={_format_log_value(value)}" for key, value in fields.items())


def _compat_events_enabled() -> bool:
    value = os.getenv(LEGACY_VIP_EVENT_COMPAT_ENV, "1").strip().lower()
    return value not in {"0", "false", "no"}


def _log_structured_info(event: str, **fields: Any) -> None:
    body = _format_event_fields(fields)
    logger.info("%s %s", event, body)

    legacy_event = LEGACY_VIP_EVENT_MAP.get(event)
    if legacy_event and _compat_events_enabled():
        logger.info(
            "%s %s deprecated=true remove_after=%s canonical=%s",
            legacy_event,
            body,
            LEGACY_VIP_EVENT_REMOVE_AFTER,
            event,
        )


def _log_vip_detection(
    *,
    sport: str,
    contest_id: int | None,
    requested: int,
    found: int,
    attempted: bool,
    reason: str,
) -> None:
    _log_structured_info(
        "vip_detection",
        sport=sport,
        contest_id=contest_id,
        requested=requested,
        found=found,
        attempted=attempted,
        reason=reason,
    )


def _log_vip_fetch(
    *,
    sport: str,
    contest_id: int | None,
    requested: int,
    fetched: int,
    missing_roster: int,
    failures: int,
    attempted: bool,
    reason: str,
) -> None:
    _log_structured_info(
        "vip_fetch",
        sport=sport,
        contest_id=contest_id,
        requested=requested,
        fetched=fetched,
        missing_roster=missing_roster,
        failures=failures,
        attempted=attempted,
        reason=reason,
    )


def _log_vip_sheet_write(
    *,
    sport: str,
    contest_id: int | None,
    lineups: int,
    written: bool,
    elapsed_ms: int,
    reason: str,
) -> None:
    _log_structured_info(
        "vip_sheet_write",
        sport=sport,
        contest_id=contest_id,
        lineups=lineups,
        written=written,
        elapsed_ms=elapsed_ms,
        reason=reason,
    )


def _log_vip_skip_events(sport_name: str, contest_id: int | None, requested: int, reason: str) -> None:
    _log_vip_detection(
        sport=sport_name,
        contest_id=contest_id,
        requested=requested,
        found=0,
        attempted=False,
        reason=reason,
    )
    _log_vip_fetch(
        sport=sport_name,
        contest_id=contest_id,
        requested=requested,
        fetched=0,
        missing_roster=0,
        failures=0,
        attempted=False,
        reason=reason,
    )
    _log_vip_sheet_write(
        sport=sport_name,
        contest_id=contest_id,
        lineups=0,
        written=False,
        elapsed_ms=0,
        reason=reason,
    )


def _build_bonus_sender() -> WebhookSender | None:
    notifications_enabled = os.getenv("DISCORD_NOTIFICATIONS_ENABLED", "true").strip().lower() not in {
        "0",
        "false",
        "no",
    }
    if not notifications_enabled:
        return None
    webhook = os.getenv("DISCORD_BONUS_WEBHOOK") or os.getenv("DISCORD_WEBHOOK")
    if not webhook:
        return None
    return WebhookSender(webhook)


def load_vips() -> list[str]:
    """
    Load VIP usernames from vips.yaml located next to this file.
    Returns an empty list if the file is missing or malformed.
    """
    vip_path = repo_file("vips.yaml")
    try:
        with open(vip_path, "r") as f:
            vips = yaml.safe_load(f) or []
        if not isinstance(vips, list):
            logger.warning("vips.yaml did not contain a list; treating as empty.")
            return []
        # Normalize to strings and strip whitespace
        return [str(x).strip() for x in vips if str(x).strip()]
    except FileNotFoundError:
        logger.warning("vips.yaml not found at %s; proceeding with empty VIP list.", vip_path)
        return []
    except Exception as e:
        logger.warning("Failed to load vips.yaml: %s; proceeding with empty VIP list.", e)
        return []


def write_players_to_sheet(
    sheet: DfsSheetService,
    results: Results,
    sport_name: str,
    now: datetime.datetime,
    dk: Draftkings,
    vips: list[str],
    draft_group: int | None = None,
) -> None:
    """
    Write player values and contest details to the sheet.

    Args:
        sheet (DfsSheetService): Sheet object.
        results (Results): Results object.
        sport_name (str): Sport name.
        now (datetime.datetime): Current datetime.
        dk (Draftkings): Authenticated DraftKings API client.
        vips (list[str]): VIP usernames loaded once at run start.
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

    dk_id = results.contest_id
    dg = draft_group
    fetch_requested = len(results.vip_list)

    if not vips:
        _log_vip_fetch(
            sport=sport_name,
            contest_id=dk_id,
            requested=0,
            fetched=0,
            missing_roster=0,
            failures=0,
            attempted=False,
            reason="empty_vip_set",
        )
        _log_vip_sheet_write(
            sport=sport_name,
            contest_id=dk_id,
            lineups=0,
            written=False,
            elapsed_ms=0,
            reason="empty_vip_lineups",
        )
        return

    if dg is None:
        logger.warning("No draft group found for sport, cannot pull VIP lineups from API.")
        _log_vip_fetch(
            sport=sport_name,
            contest_id=dk_id,
            requested=fetch_requested,
            fetched=0,
            missing_roster=fetch_requested,
            failures=0,
            attempted=False,
            reason="no_draft_group",
        )
        _log_vip_sheet_write(
            sport=sport_name,
            contest_id=dk_id,
            lineups=0,
            written=False,
            elapsed_ms=0,
            reason="no_draft_group",
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
    player_salary_map: dict[str, int] = {name: player.salary for name, player in results.players.items()}
    fetch_failures = 0
    fetch_reason = "not_applicable"
    try:
        vip_lineups: list[dict] = dk.get_vip_lineups(
            dk_id,
            dg,
            vips,
            vip_entries=vip_entries,
            player_salary_map=player_salary_map,
        )
        if not vip_lineups:
            fetch_reason = "empty_vip_lineups"
    except Exception:
        fetch_failures = 1
        fetch_reason = "fetch_error"
        vip_lineups = []
        logger.exception("Failed VIP lineup fetch: sport=%s contest_id=%s", sport_name, dk_id)

    fetched_count = len(vip_lineups)
    _log_vip_fetch(
        sport=sport_name,
        contest_id=dk_id,
        requested=fetch_requested,
        fetched=fetched_count,
        missing_roster=max(fetch_requested - fetched_count, 0),
        failures=fetch_failures,
        attempted=True,
        reason=fetch_reason,
    )

    if vip_lineups:
        started = time.perf_counter()
        sheet.clear_lineups()
        sheet.write_vip_lineups(vip_lineups)
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        _log_vip_sheet_write(
            sport=sport_name,
            contest_id=dk_id,
            lineups=len(vip_lineups),
            written=True,
            elapsed_ms=elapsed_ms,
            reason="not_applicable",
        )
        bonus_sender = _build_bonus_sender()
        if bonus_sender:
            try:
                with sqlite3.connect(str(state.contests_db_path())) as conn:
                    announce_vip_bonuses(
                        conn=conn,
                        sport=sport_name,
                        contest_id=dk_id,
                        vip_lineups=vip_lineups,
                        sender=bonus_sender,
                        logger=logger,
                    )
            except sqlite3.Error as err:
                logger.error(
                    "Failed bonus announcement DB flow for %s (%s): %s",
                    sport_name,
                    dk_id,
                    err,
                )
    else:
        _log_vip_sheet_write(
            sport=sport_name,
            contest_id=dk_id,
            lineups=0,
            written=False,
            elapsed_ms=0,
            reason="empty_vip_lineups",
        )


def write_non_cashing_info(sheet: DfsSheetService, results: Results) -> None:
    """
    Write non-cashing user info to the sheet.

    Args:
        sheet (DfsSheetService): Sheet object.
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
            top_ten_players = [p for p, _ in list(sorted_non_cashing_players.items())[:10]]
            for p in top_ten_players:
                count = results.non_cashing_players[p]
                ownership = float(count / results.non_cashing_users)
                info.append([p, ownership])
        sheet.add_non_cashing_info(info)


def write_train_info(sheet: DfsSheetService, results: Results) -> None:
    """
    Write train info to the sheet.

    Args:
        sheet (DfsSheetService): Sheet object.
        results (Results): Results object.
    """
    if results and results.users:
        trainfinder = TrainFinder(results.users)
        total_users = trainfinder.get_total_users()
        users_above_salary = trainfinder.get_total_users_above_salary(SALARY_LIMIT)
        logger.info(
            "train_summary total_users=%d salary_limit=%d users_above_salary=%d",
            total_users,
            SALARY_LIMIT,
            users_above_salary,
        )

        trains: dict[str, dict[str, Any]] = trainfinder.get_users_above_salary_spent(SALARY_LIMIT)
        delete_keys = [key for key in trains if trains[key]["count"] == 1]
        for key in delete_keys:
            del trains[key]
        sorted_trains: OrderedDict[str, dict[str, Any]] = OrderedDict(
            sorted(trains.items(), key=lambda kv: kv[1]["count"], reverse=True)[:5]
        )
        info: list[list[Any]] = [
            ["Rank", "Users", "Score", "PMR"],
        ]
        for v in sorted_trains.values():
            row = [v["rank"], v["count"], v["pts"], v["pmr"]]
            logger.debug("train users=%s score=%s pmr=%s lineup=%s", v["count"], v["pts"], v["pmr"], v["lineup"])
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
) -> int | None:
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
    result = contest_database.get_live_contest(sport_obj.name, sport_obj.sheet_min_entry_fee, sport_obj.keyword)
    if not result:
        logger.warning("There are no live contests for %s! Moving on.", sport_name)
        _log_vip_skip_events(sport_name, None, len(vips), "not_applicable")
        return None

    dk_id, name, draft_group, positions_paid, _start_date = result
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
        _log_vip_skip_events(sport_name, int(dk_id), len(vips), "standings_unavailable")
        return None

    sheet = build_dfs_sheet_service(sport_name)
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
    _log_vip_detection(
        sport=sport_name,
        contest_id=int(dk_id),
        requested=len(vips),
        found=len(results.vip_list),
        attempted=True,
        reason="empty_vip_set" if not vips else "not_applicable",
    )

    try:
        if (sport_obj.allow_optimizer is False) or (not args.nolineups):
            logger.info("Skipping optimal lineup for %s", sport_name)
        else:
            p = results.get_players()
            optimizer = Optimizer(sport_obj, p)
            optimized_players = optimizer.get_optimal_lineup()
            if optimized_players:
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
                        f"Player [{player.pos}]: {player.name} Score: {player.fpts} Salary: "
                        f"{player.salary} Value {player.value} Own: {player.ownership}"
                    )
                    optimized_info.append(row)
                sheet.add_optimal_lineup(optimized_info)
                logger.debug(optimized_players)
    except Exception as error:
        logger.error(error)
        logger.error("Error in optimal lineup")

    write_players_to_sheet(sheet, results, sport_name, now, dk, vips, draft_group)
    write_non_cashing_info(sheet, results)
    write_train_info(sheet, results)
    return int(dk_id)


def build_snapshot_payload(
    selected_contests: dict[str, int],
    standings_limit: int = DEFAULT_STANDINGS_LIMIT,
) -> dict[str, Any]:
    generated_at = to_utc_iso(datetime.datetime.now(datetime.timezone.utc))
    sports: dict[str, Any] = {}
    for sport_name in sorted(selected_contests):
        contest_id = selected_contests[sport_name]
        snapshot = build_snapshot(
            sport=sport_name,
            contest_id=contest_id,
            standings_limit=standings_limit,
        )
        sports[sport_name.lower()] = normalize_snapshot_for_output(snapshot)

    return {
        "schema_version": 2,
        "snapshot_at": generated_at,
        "generated_at": generated_at,
        "sports": sports,
    }


def write_snapshot_payload(path: pathlib.Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(to_stable_json(payload), encoding="utf-8")


def main() -> None:
    """
    Use database and update Google Sheet with contest standings from DraftKings.
    """
    load_dotenv()
    load_and_apply_settings()

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
    parser.add_argument("-v", "--verbose", action="store_true", help="Increase verbosity")
    parser.add_argument(
        "--snapshot-out",
        help="Optional path to write a multi-sport snapshot envelope for selected contests.",
    )
    parser.add_argument(
        "--standings-limit",
        type=int,
        default=DEFAULT_STANDINGS_LIMIT,
        help="Standings row limit used for snapshot export output.",
    )
    args = parser.parse_args()
    configure_logging(level_override="DEBUG" if args.verbose else None)
    contest_database = ContestDatabase(str(state.contests_db_path()))
    vips = load_vips()
    now = datetime.datetime.now(ZoneInfo("America/New_York"))
    selected_contests: dict[str, int] = {}
    for sport_name in args.sport:
        selected_id = process_sport(sport_name, choices, contest_database, now, args, vips)
        if selected_id is not None:
            selected_contests[sport_name] = selected_id

    if args.snapshot_out:
        payload = build_snapshot_payload(
            selected_contests,
            standings_limit=args.standings_limit,
        )
        out_path = pathlib.Path(args.snapshot_out)
        write_snapshot_payload(out_path, payload)
        logger.info("snapshot selected_contests=%d", len(selected_contests))
        logger.info("snapshot output path=%s", out_path)


if __name__ == "__main__":
    main()
