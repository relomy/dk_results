"""Shared fakes and builders for the db_main test modules."""

import datetime
from collections.abc import Callable
from pathlib import Path
from typing import Any

import requests

from dk_results.domain.contest_standings import ContestStandings
from dk_results.domain.sport import Sport
from dk_results.domain.user import User
from dk_results.persistence.contestdatabase import ContestDatabase
from dk_results.sport_processor import (
    SportProcessor,
    SportProcessorConfig,
)


def _salary_csv_text() -> str:
    return (
        "Position,ID,Name,ID2,Roster Position,Salary,Game Info,TeamAbbrev,AvgPoints\n"
        "QB,,Tom Brady,,QB,7000,NE@NYJ 1:00PM ET,NE,0\n"
        "RB,,Derrick Henry,,RB/FLEX,8000,TEN@IND 1:00PM ET,TEN,0\n"
    )


def _standings_rows() -> list[list[str]]:
    return [
        [
            "Rank",
            "EntryId",
            "EntryName",
            "TimeRemaining",
            "Points",
            "Lineup",
            "",
            "Player",
            "Roster Position",
            "%Drafted",
            "FPTS",
        ],
        [
            "1",
            "111",
            "UserA",
            "0",
            "120",
            "QB Tom Brady RB Derrick Henry",
            "",
            "",
            "",
            "",
            "",
        ],
        ["", "", "", "", "", "", "", "Tom Brady", "QB", "50.00%", "20"],
        ["", "", "", "", "", "", "", "", "", "", ""],
    ]


class _FakeContestDb:
    def __init__(self):
        self.cash_lines: dict[int, tuple[int | None, float | None]] = {}
        self.vip_statuses: dict[int, list] = {}

    def get_live_contest(self, *_args, **_kwargs):
        return (
            123,
            "Test Contest",
            999,
            1,
            "2026-02-14 01:00:00",
        )

    def set_cash_line(self, dk_id, rank, points):
        self.cash_lines[dk_id] = (rank, points)

    def replace_vip_cash_status(self, dk_id, statuses):
        self.vip_statuses[dk_id] = statuses


class _FakeDraftKings:
    def download_salary_csv(self, sport: str, draft_group: int, filename: str) -> None:
        path = Path(filename)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_salary_csv_text(), encoding="utf-8")

    def download_contest_rows(self, *_args, **_kwargs):
        return _standings_rows()

    def get_leaderboard(self, contest_id: int, *, timeout: int | None = None) -> dict[str, Any]:
        raise NotImplementedError

    def get_entry(
        self,
        draft_group: int,
        entry_key: str,
        *,
        timeout: int | None = None,
        session: requests.Session | None = None,
    ) -> dict[str, Any]:
        raise NotImplementedError

    def clone_auth_to(self, target_session: requests.Session) -> None:
        pass


class _FakeSheet:
    def __init__(self):
        self.players = []

    def clear_standings(self):
        return None

    def write_players(self, values, format_plan=()):
        self.players = list(values)

    def add_contest_details(self, *_args, **_kwargs):
        return None

    def add_last_updated(self, *_args, **_kwargs):
        return None

    def add_min_cash(self, *_args, **_kwargs):
        return None

    def clear_lineups(self):
        return None

    def write_vip_lineups(self, *_args, **_kwargs):
        return None

    def add_non_cashing_info(self, *_args, **_kwargs):
        return None

    def add_train_info(self, *_args, **_kwargs):
        return None

    def add_optimal_lineup(self, *_args, **_kwargs):
        return None


def _make_processor(
    db,
    vips,
    *,
    dk=None,
    sheet=None,
    nolineups: bool = False,
    salary_dir: str = "",
    bonus_sender=None,
) -> SportProcessor:
    if dk is None:
        dk = _FakeDraftKings()
    if sheet is None:
        sheet = _FakeSheet()
    return SportProcessor(
        contest_db=db,
        dk=dk,
        sheet_factory=lambda _sport: sheet,
        bonus_sender=bonus_sender,
        config=SportProcessorConfig(
            salary_dir=salary_dir,
            contest_dir=".",
            cookies_file=".",
            write_optimal_lineup=nolineups,
        ),
        now=datetime.datetime(2026, 2, 14, 12, 0, 0),
        vips=vips,
    )


class _ScriptedProcessor(SportProcessor):
    """A SportProcessor whose ``run`` outcome is scripted by the test."""

    def __init__(self, run: Callable[[str, type[Sport]], int]):
        super().__init__(
            contest_db=ContestDatabase(":memory:"),
            dk=_FakeDraftKings(),
            sheet_factory=lambda _sport: _FakeSheet(),
            bonus_sender=None,
            config=SportProcessorConfig(salary_dir="", contest_dir=".", cookies_file="."),
            now=datetime.datetime(2026, 2, 14, 12, 0, 0),
            vips=[],
        )
        self._run = run

    def run(self, sport_name: str, sport_cls: type[Sport]) -> int:
        return self._run(sport_name, sport_cls)


def _make_standings(*, users: list[User] | None = None) -> ContestStandings:
    return ContestStandings(
        players={},
        users=users or [],
        vip_list=[],
        positions_paid=None,
        min_rank=0,
        min_cash_pts=0.0,
        non_cashing_users=0,
        non_cashing_avg_pmr=0.0,
        non_cashing_players={},
    )
