import datetime
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, ClassVar

import pytest
import requests

from dk_results.domain.contest_standings import ContestStandings
from dk_results.domain.sport import Sport
from dk_results.domain.user import User
from dk_results.persistence.contestdatabase import ContestDatabase
from dk_results.sport_processor import (
    SportProcessor,
    SportProcessorConfig,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"

for path in (REPO_ROOT, SRC_ROOT):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)


class _StubLobbyResponse:
    """Stand-in for a requests.Response carrying a fixed JSON payload."""

    status_code = 200

    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


@pytest.fixture
def anonymous_lobby(monkeypatch):
    """Exercise the real DraftKings client on an unauthenticated lobby read.

    Trips (AssertionError) if the path constructs ``AuthSession`` or calls
    ``get_dk_cookies`` — the yt-dlp cookie extraction that regressed
    ``dkcontests.py`` latency (ADR-0009, #102). Returns a ``serve(payload)``
    callable that stubs ``Session.get`` so no network I/O happens; the real
    ``DraftKings.__init__`` / session construction still runs.
    """
    from dk_results.draftkings import client as dk_client_module
    from dk_results.draftkings import session as dk_session_module

    def _forbid(name):
        def _boom(*_args, **_kwargs):
            raise AssertionError(f"lobby reads must not reach {name} (ADR-0009)")

        return _boom

    monkeypatch.setattr(dk_client_module, "AuthSession", _forbid("AuthSession"))
    monkeypatch.setattr(dk_session_module, "get_dk_cookies", _forbid("get_dk_cookies"))

    def serve(payload):
        monkeypatch.setattr(
            "requests.sessions.Session.get",
            lambda self, *args, **kwargs: _StubLobbyResponse(payload),
        )

    return serve


# ── db_main: edge fakes, their variants and SportProcessor builders ──────────


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


def _standings_rows_with_missing_vip_entry() -> list[list[str]]:
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
        [
            "2",
            "",
            "UserB",
            "0",
            "110",
            "QB Tom Brady RB Derrick Henry",
            "",
            "",
            "",
            "",
            "",
        ],
        ["", "", "", "", "", "", "", "Tom Brady", "QB", "50.00%", "20"],
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

    def persist_standings_cash_snapshot(self, dk_id, rank, points, statuses):
        self.cash_lines[dk_id] = (rank, points)
        self.vip_statuses[dk_id] = statuses


class _FakeContestDbNoLive:
    def get_live_contest(self, *_args, **_kwargs):
        return None


class _FakeContestDbNoPositionsPaid(_FakeContestDb):
    def get_live_contest(self, *_args, **_kwargs):
        return (
            123,
            "Test Contest",
            999,
            None,
            "2026-02-14 01:00:00",
        )


class _FakeContestDbNoDraftGroup(_FakeContestDb):
    def get_live_contest(self, *_args, **_kwargs):
        return (
            123,
            "Test Contest",
            None,
            1,
            "2026-02-14 01:00:00",
        )


class _FakeContestDbTwoPaid(_FakeContestDb):
    def get_live_contest(self, *_args, **_kwargs):
        return (123, "Test Contest", 999, 2, "2026-02-14 01:00:00")


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


class _FakeDraftKingsNoStandings(_FakeDraftKings):
    def download_contest_rows(self, *_args, **_kwargs):
        return None


class _FakeDraftKingsTrackVipEntries(_FakeDraftKings):
    captured_vip_entries: ClassVar[dict] = {}

    def download_contest_rows(self, *_args, **_kwargs):
        return _standings_rows_with_missing_vip_entry()


class _FakeDraftKingsTiedAtTop(_FakeDraftKings):
    def download_contest_rows(self, *_args, **_kwargs):
        both = "QB Tom Brady RB Derrick Henry"
        return [
            ["Rank", "EntryId", "EntryName", "TimeRemaining", "Points", "Lineup"],
            ["1", "111", "UserA", "0", "120", both],
            ["2", "222", "UserB", "0", "120", both],
            ["3", "333", "UserC", "30", "100", "RB Derrick Henry"],
        ]


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


class _CapturingSheet(_FakeSheet):
    def __init__(self):
        super().__init__()
        self.non_cashing_info = None

    def add_non_cashing_info(self, info):
        self.non_cashing_info = info


def _build_processor(
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
            # ``run`` is overridden, so the database is never read: skip opening a real connection.
            contest_db=ContestDatabase.__new__(ContestDatabase),
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


@pytest.fixture
def salary_csv_text() -> str:
    return _salary_csv_text()


@pytest.fixture
def live_contest_db() -> _FakeContestDb:
    """The default live contest: 123, one position paid, a draft group."""
    return _FakeContestDb()


@pytest.fixture
def contest_db_no_live() -> _FakeContestDbNoLive:
    return _FakeContestDbNoLive()


@pytest.fixture
def contest_db_no_positions_paid() -> _FakeContestDbNoPositionsPaid:
    return _FakeContestDbNoPositionsPaid()


@pytest.fixture
def contest_db_no_draft_group() -> _FakeContestDbNoDraftGroup:
    return _FakeContestDbNoDraftGroup()


@pytest.fixture
def contest_db_two_paid() -> _FakeContestDbTwoPaid:
    return _FakeContestDbTwoPaid()


@pytest.fixture
def dk_no_standings() -> _FakeDraftKingsNoStandings:
    return _FakeDraftKingsNoStandings()


@pytest.fixture
def dk_track_vip_entries() -> _FakeDraftKingsTrackVipEntries:
    return _FakeDraftKingsTrackVipEntries()


@pytest.fixture
def dk_tied_at_top() -> _FakeDraftKingsTiedAtTop:
    return _FakeDraftKingsTiedAtTop()


@pytest.fixture
def fake_sheet() -> _FakeSheet:
    return _FakeSheet()


@pytest.fixture
def capturing_sheet() -> _CapturingSheet:
    return _CapturingSheet()


@pytest.fixture
def make_sport_processor() -> Callable[..., SportProcessor]:
    """``make_processor(db, vips=..., dk=..., sheet=..., nolineups=..., salary_dir=..., bonus_sender=...)``."""
    return _build_processor


@pytest.fixture
def make_scripted_processor() -> Callable[[Callable[[str, type[Sport]], int]], SportProcessor]:
    """``make_scripted_processor(run)``: a processor whose ``run`` is the given callable."""
    return _ScriptedProcessor


@pytest.fixture
def make_standings() -> Callable[..., ContestStandings]:
    def build(*, users: list[User] | None = None) -> ContestStandings:
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

    return build
