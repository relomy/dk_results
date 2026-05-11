from __future__ import annotations

import csv
import datetime
import logging
import os
import sqlite3
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Callable, Protocol, runtime_checkable

import requests
from dfs_common import state

from dk_results.classes.bonus_announcements import announce_vip_bonuses
from dk_results.classes.contest_standings import ContestStandings, parse_contest_standings, players_to_values
from dk_results.classes.contestdatabase import ContestDatabase
from dk_results.classes.optimizer import Optimizer
from dk_results.classes.sport import Sport
from dk_results.classes.trainfinder import TrainFinder
from dk_results.vip_lineups import build_vip_entries, fetch_vip_lineups

logger = logging.getLogger(__name__)

_LEGACY_VIP_EVENT_COMPAT_ENV = "DK_VIP_EVENT_COMPAT"
_LEGACY_VIP_EVENT_REMOVE_AFTER = "2026-04-30"
_LEGACY_VIP_EVENT_MAP = {
    "vip_detection": "vip_detection_summary",
    "vip_fetch": "vip_lineups_fetch",
    "vip_sheet_write": "vip_lineups_summary",
}


# ── Ports ──────────────────────────────────────────────────────────────────────


@runtime_checkable
class DkPort(Protocol):
    def download_salary_csv(self, sport: str, draft_group: int, filename: str) -> None: ...
    def download_contest_rows(
        self,
        contest_id: int,
        *,
        timeout: int = 30,
        cookies_dump_file: str | None = None,
        contest_dir: str | None = None,
    ) -> list[list[str]] | None: ...
    def get_leaderboard(self, contest_id: int, *, timeout: int | None = None) -> dict[str, Any]: ...
    def get_entry(
        self,
        draft_group: int,
        entry_key: str,
        *,
        timeout: int | None = None,
        session: requests.Session | None = None,
    ) -> dict[str, Any]: ...
    def clone_auth_to(self, target_session: requests.Session) -> None: ...


@runtime_checkable
class SheetPort(Protocol):
    def clear_standings(self) -> None: ...
    def clear_lineups(self) -> None: ...
    def write_players(self, values: Any) -> None: ...
    def add_contest_details(self, contest_name: str, positions_paid: int | None) -> None: ...
    def add_last_updated(self, dt: datetime.datetime) -> None: ...
    def add_min_cash(self, pts: float) -> None: ...
    def write_vip_lineups(self, lineups: list[dict[str, Any]]) -> None: ...
    def add_non_cashing_info(self, info: list[list[Any]]) -> None: ...
    def add_train_info(self, info: list[list[Any]]) -> None: ...
    def add_optimal_lineup(self, info: list[list[Any]]) -> None: ...


@runtime_checkable
class BonusSenderPort(Protocol):
    def send_message(self, message: str) -> None: ...


# ── Config ─────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class SportProcessorConfig:
    salary_dir: str
    contest_dir: str
    cookies_file: str
    salary_limit: int = 40_000
    write_optimal_lineup: bool = True


# ── Exceptions ─────────────────────────────────────────────────────────────────


class NoLiveContestError(Exception):
    pass


class StandingsUnavailableError(Exception):
    pass


class StandsParseError(Exception):
    pass


# ── Module ─────────────────────────────────────────────────────────────────────


class SportProcessor:
    """
    Coordinates the full "process one sport → write sheet" workflow.

    Construction-time dependencies are injected; nothing is constructed inline.
    One instance may be reused across multiple sports in a single run.

    Ordering guarantee (enforced internally):
      1. DB lookup → NoLiveContestError if no contest
      2. Salary CSV download
      3. Contest standings download → StandingsUnavailableError if empty
      4. Parse standings → StandsParseError on failure
      5. Sheet writes (clear → players → VIP lineups → non-cashing → train)
      6. Bonus announcements (after VIP lineups written)

    Not idempotent: sheet writes are destructive (clear then write).
    """

    def __init__(
        self,
        *,
        contest_db: ContestDatabase,
        dk: DkPort,
        sheet_factory: Callable[[str], SheetPort],
        bonus_sender: BonusSenderPort | None,
        config: SportProcessorConfig,
        now: datetime.datetime,
        vips: list[str],
    ) -> None:
        self._db = contest_db
        self._dk = dk
        self._sheet_factory = sheet_factory
        self._bonus_sender = bonus_sender
        self._config = config
        self._now = now
        self._vips = vips

    def run(self, sport_name: str, sport_cls: type[Sport]) -> int:
        """
        Process one sport end-to-end: DB lookup → download → parse → sheet write.

        Returns the DraftKings contest_id on success.
        Raises NoLiveContestError, StandingsUnavailableError, or StandsParseError
        when the sport must be skipped; callers should catch and continue.
        """
        result = self._db.get_live_contest(sport_cls.name, sport_cls.sheet_min_entry_fee, sport_cls.keyword)
        if not result:
            logger.warning("There are no live contests for %s! Moving on.", sport_name)
            self._log_vip_skip_events(sport_name, None, len(self._vips), "not_applicable")
            raise NoLiveContestError(sport_name)

        dk_id, name, draft_group, positions_paid, _start_date = result
        fn = os.path.join(self._config.salary_dir, f"DKSalaries_{sport_name}_{self._now:%A}.csv")

        if draft_group:
            logger.info("Downloading salary file (draft_group: %d)", draft_group)
            self._dk.download_salary_csv(sport_name, draft_group, fn)

        contest_list = self._dk.download_contest_rows(
            dk_id,
            timeout=30,
            cookies_dump_file=self._config.cookies_file,
            contest_dir=self._config.contest_dir,
        )
        if not contest_list:
            logger.warning("Contest standings download failed or was empty for dk_id=%s; skipping.", dk_id)
            self._log_vip_skip_events(sport_name, int(dk_id), len(self._vips), "standings_unavailable")
            raise StandingsUnavailableError(sport_name)

        sheet = self._sheet_factory(sport_name)

        try:
            results = self._build_results(
                sport_cls=sport_cls,
                contest_id=int(dk_id),
                salary_csv=fn,
                positions_paid=positions_paid,
                standings_rows=contest_list,
            )
        except Exception:
            logger.exception("Failed to parse contest standings: sport=%s contest_id=%s", sport_name, dk_id)
            self._log_vip_skip_events(sport_name, int(dk_id), len(self._vips), "results_unavailable")
            raise StandsParseError(sport_name)

        self._maybe_write_optimal_lineup(sheet=sheet, results=results, sport_cls=sport_cls, sport_name=sport_name)
        self._write_standings(sheet, results, sport_name, int(dk_id), name, positions_paid)
        self._write_vip_lineups(sheet, results, sport_name, int(dk_id), draft_group)
        self._write_non_cashing_info(sheet, results)
        self._write_train_info(sheet, results)

        return int(dk_id)

    # ── Private workflow steps ─────────────────────────────────────────────────

    def _build_results(
        self,
        *,
        sport_cls: type[Sport],
        contest_id: int,
        salary_csv: str,
        positions_paid: int | None,
        standings_rows: list[list[str]],
    ) -> ContestStandings:
        logger.debug("Parsing contest standings: sport=%s contest_id=%s", sport_cls.name, contest_id)
        with open(salary_csv, mode="r") as fp:
            salary_rows = list(csv.reader(fp, delimiter=","))
        return parse_contest_standings(
            sport_cls,
            salary_rows,
            standings_rows,
            positions_paid=positions_paid,
            vips=self._vips,
        )

    def _maybe_write_optimal_lineup(
        self,
        *,
        sheet: SheetPort,
        results: ContestStandings,
        sport_cls: type[Sport],
        sport_name: str,
    ) -> None:
        try:
            if (sport_cls.allow_optimizer is False) or (not self._config.write_optimal_lineup):
                logger.info("Skipping optimal lineup for %s", sport_name)
                return

            optimizer = Optimizer(sport_cls, results.players)
            optimized_players = optimizer.get_optimal_lineup()
            if optimized_players:
                optimized_players.sort(key=lambda x: (sport_cls.positions.index(x.pos), x.name))
            if not optimized_players:
                return

            optimized_info: list[list[Any]] = [["Pos", "Name", "Salary", "Pts", "Value", "Own%"]]
            for player in optimized_players:
                row = [player.pos, player.name, player.salary, player.fpts, player.value, player.ownership]
                logger.info(
                    "Player [%s]: %s Score: %s Salary: %s Value %s Own: %s",
                    player.pos,
                    player.name,
                    player.fpts,
                    player.salary,
                    player.value,
                    player.ownership,
                )
                optimized_info.append(row)
            sheet.add_optimal_lineup(optimized_info)
            logger.debug(optimized_players)
        except Exception as error:
            logger.error(error)
            logger.error("Error in optimal lineup")

    def _write_standings(
        self,
        sheet: SheetPort,
        results: ContestStandings,
        sport_name: str,
        dk_id: int,
        contest_name: str,
        positions_paid: int | None,
    ) -> None:
        sheet.clear_standings()
        sheet.write_players(players_to_values(results.players, sport_name))
        sheet.add_contest_details(contest_name, positions_paid)
        logger.info("Writing players to sheet")
        sheet.add_last_updated(self._now)
        if results.min_cash_pts > 0:
            logger.info("Writing min_cash_pts: %d", results.min_cash_pts)
            sheet.add_min_cash(results.min_cash_pts)

    def _write_vip_lineups(
        self,
        sheet: SheetPort,
        results: ContestStandings,
        sport_name: str,
        dk_id: int,
        draft_group: int | None,
    ) -> None:
        self._log_vip_detection(
            sport=sport_name,
            contest_id=dk_id,
            requested=len(self._vips),
            found=len(results.vip_list),
            attempted=True,
            reason="empty_vip_set" if not self._vips else "not_applicable",
        )

        requested_vips = len(results.vip_list)

        if not self._vips:
            self._log_vip_fetch(
                sport=sport_name,
                contest_id=dk_id,
                requested=0,
                fetched=0,
                missing_roster=0,
                failures=0,
                attempted=False,
                reason="empty_vip_set",
            )
            self._log_vip_sheet_write(
                sport=sport_name,
                contest_id=dk_id,
                lineups=0,
                written=False,
                elapsed_ms=0,
                reason="empty_vip_lineups",
            )
            return

        if draft_group is None:
            logger.warning("No draft group found for sport, cannot pull VIP lineups from API.")
            self._log_vip_fetch(
                sport=sport_name,
                contest_id=dk_id,
                requested=requested_vips,
                fetched=0,
                missing_roster=requested_vips,
                failures=0,
                attempted=False,
                reason="no_draft_group",
            )
            self._log_vip_sheet_write(
                sport=sport_name,
                contest_id=dk_id,
                lineups=0,
                written=False,
                elapsed_ms=0,
                reason="no_draft_group",
            )
            return

        vip_entries = build_vip_entries(results.vip_list)
        fetch_requested = len(vip_entries) if vip_entries else requested_vips
        player_salary_map: dict[str, int] = {n: p.salary for n, p in results.players.items()}
        fetch_failures = 0
        fetch_reason = "not_applicable"
        try:
            raw_lineups = fetch_vip_lineups(
                dk_id,
                draft_group,
                self._dk,
                vips=self._vips,
                vip_entries=vip_entries,
                player_salary_map=player_salary_map,
            )
            vip_lineups = [vl.to_dict() for vl in raw_lineups]
            if not vip_lineups:
                fetch_reason = "empty_vip_lineups"
        except Exception:
            fetch_failures = 1
            fetch_reason = "fetch_error"
            vip_lineups = []
            logger.exception("Failed VIP lineup fetch: sport=%s contest_id=%s", sport_name, dk_id)

        fetched_count = len(vip_lineups)
        self._log_vip_fetch(
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
            self._log_vip_sheet_write(
                sport=sport_name,
                contest_id=dk_id,
                lineups=len(vip_lineups),
                written=True,
                elapsed_ms=elapsed_ms,
                reason="not_applicable",
            )
            if self._bonus_sender:
                try:
                    with sqlite3.connect(str(state.contests_db_path())) as conn:
                        announce_vip_bonuses(
                            conn=conn,
                            sport=sport_name,
                            contest_id=dk_id,
                            vip_lineups=vip_lineups,
                            sender=self._bonus_sender,
                            logger=logger,
                        )
                except sqlite3.Error as err:
                    logger.error("Failed bonus announcement DB flow for %s (%s): %s", sport_name, dk_id, err)
        else:
            self._log_vip_sheet_write(
                sport=sport_name,
                contest_id=dk_id,
                lineups=0,
                written=False,
                elapsed_ms=0,
                reason=fetch_reason,
            )

    def _write_non_cashing_info(self, sheet: SheetPort, results: ContestStandings) -> None:
        if results.non_cashing_users > 0:
            logger.info("Writing non_cashing info")
            info: list[list[Any]] = [
                ["Non-Cashing Info", ""],
                ["Users not cashing", results.non_cashing_users],
                ["Avg PMR Remaining", results.non_cashing_avg_pmr],
            ]
            if results.non_cashing_players:
                info.append(["Top 10 Own% Remaining", ""])
                sorted_non_cashing: dict[str, int] = {
                    k: v for k, v in sorted(results.non_cashing_players.items(), key=lambda item: item[1], reverse=True)
                }
                for p, count in list(sorted_non_cashing.items())[:10]:
                    info.append([p, float(count / results.non_cashing_users)])
            sheet.add_non_cashing_info(info)

    def _write_train_info(self, sheet: SheetPort, results: ContestStandings) -> None:
        if not (results and results.users):
            return
        trainfinder = TrainFinder(results.users)
        total_users = trainfinder.get_total_users()
        users_above_salary = trainfinder.get_total_users_above_salary(self._config.salary_limit)
        logger.info(
            "train_summary total_users=%d salary_limit=%d users_above_salary=%d",
            total_users,
            self._config.salary_limit,
            users_above_salary,
        )
        trains: dict[str, dict[str, Any]] = trainfinder.get_users_above_salary_spent(self._config.salary_limit)
        for key in [k for k in trains if trains[k]["count"] == 1]:
            del trains[key]
        sorted_trains: OrderedDict[str, dict[str, Any]] = OrderedDict(
            sorted(trains.items(), key=lambda kv: kv[1]["count"], reverse=True)[:5]
        )
        info: list[list[Any]] = [["Rank", "Users", "Score", "PMR"]]
        for v in sorted_trains.values():
            row = [v["rank"], v["count"], v["pts"], v["pmr"]]
            logger.debug("train users=%s score=%s pmr=%s lineup=%s", v["count"], v["pts"], v["pmr"], v["lineup"])
            if v["lineup"]:
                row.extend([player.name for player in v["lineup"].lineup])
            info.append(row)
        sheet.add_train_info(info)

    # ── Structured logging ─────────────────────────────────────────────────────

    @staticmethod
    def _format_log_value(value: Any) -> str:
        if isinstance(value, bool):
            return str(value).lower()
        if value is None:
            return "none"
        return str(value)

    @classmethod
    def _format_event_fields(cls, fields: dict[str, Any]) -> str:
        return " ".join(f"{k}={cls._format_log_value(v)}" for k, v in fields.items())

    @staticmethod
    def _compat_events_enabled() -> bool:
        value = os.getenv(_LEGACY_VIP_EVENT_COMPAT_ENV, "1").strip().lower()
        return value not in {"0", "false", "no"}

    @classmethod
    def _log_structured_info(cls, event: str, **fields: Any) -> None:
        body = cls._format_event_fields(fields)
        logger.info("%s %s", event, body)
        legacy_event = _LEGACY_VIP_EVENT_MAP.get(event)
        if legacy_event and cls._compat_events_enabled():
            logger.info(
                "%s %s deprecated=true remove_after=%s canonical=%s",
                legacy_event,
                body,
                _LEGACY_VIP_EVENT_REMOVE_AFTER,
                event,
            )

    @classmethod
    def _log_vip_detection(
        cls, *, sport: str, contest_id: int | None, requested: int, found: int, attempted: bool, reason: str
    ) -> None:
        cls._log_structured_info(
            "vip_detection",
            sport=sport,
            contest_id=contest_id,
            requested=requested,
            found=found,
            attempted=attempted,
            reason=reason,
        )

    @classmethod
    def _log_vip_fetch(
        cls,
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
        cls._log_structured_info(
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

    @classmethod
    def _log_vip_sheet_write(
        cls,
        *,
        sport: str,
        contest_id: int | None,
        lineups: int,
        written: bool,
        elapsed_ms: int,
        reason: str,
    ) -> None:
        cls._log_structured_info(
            "vip_sheet_write",
            sport=sport,
            contest_id=contest_id,
            lineups=lineups,
            written=written,
            elapsed_ms=elapsed_ms,
            reason=reason,
        )

    @classmethod
    def _log_vip_skip_events(cls, sport_name: str, contest_id: int | None, requested: int, reason: str) -> None:
        cls._log_vip_detection(
            sport=sport_name,
            contest_id=contest_id,
            requested=requested,
            found=0,
            attempted=False,
            reason=reason,
        )
        cls._log_vip_fetch(
            sport=sport_name,
            contest_id=contest_id,
            requested=requested,
            fetched=0,
            missing_roster=0,
            failures=0,
            attempted=False,
            reason=reason,
        )
        cls._log_vip_sheet_write(
            sport=sport_name,
            contest_id=contest_id,
            lineups=0,
            written=False,
            elapsed_ms=0,
            reason=reason,
        )
