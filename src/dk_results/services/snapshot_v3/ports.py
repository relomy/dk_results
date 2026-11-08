"""The replaceable edges the snapshot collector reads through: DraftKings and the contest DB.

Both ports list only what the collector calls, so a test fake can stand in for the
real ``DraftKings`` client or ``ContestDatabase`` and type-check against the same seam.
"""

from __future__ import annotations

from typing import Any, Protocol

from dk_results.persistence.contestdatabase import ContestRow
from dk_results.vip_lineups import DkHttpPort


class SnapshotDkPort(DkHttpPort, Protocol):
    """DraftKings reads the collector makes, plus the VIP lineup fetch surface of ``DkHttpPort``."""

    def get_contest_detail(self, dk_id: int, /) -> dict[str, Any]: ...
    def get_draftables(self, draft_group: int, /) -> dict[str, Any]: ...
    def download_salary_csv(self, sport: str, draft_group: int, filename: str, /) -> None: ...
    def download_contest_rows(
        self,
        contest_id: int,
        /,
        *,
        timeout: int = 30,
        cookies_dump_file: str | None = None,
        contest_dir: str | None = None,
    ) -> list[list[str]] | None: ...


class SnapshotContestDbPort(Protocol):
    """Contest database reads the collector makes."""

    def get_contest_by_id(self, dk_id: int, /) -> ContestRow | None: ...
    def get_live_contest(self, sport: str, entry_fee: int, keyword: str, /) -> tuple | None: ...
    def get_live_contest_candidates(
        self, sport: str, /, *, entry_fee: int, keyword: str, limit: int
    ) -> list[tuple]: ...
    def get_contest_state(self, dk_id: int, /) -> tuple[str | None, int | None] | None: ...
    def get_contest_completed_at(self, dk_id: int, /) -> str | None: ...
    def get_contest_contract_metadata(
        self, dk_id: int, /
    ) -> tuple[int | None, int | None, int | None, int | None] | None: ...
    def close(self) -> None: ...
