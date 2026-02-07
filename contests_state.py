from __future__ import annotations

import logging
from pathlib import Path

from dfs_common import contests, state

from classes.contest import Contest

_UNSET = object()


def contests_db_path() -> Path:
    path = state.contests_db_path()
    logging.getLogger(__name__).info("Using contests DB at %s", path)
    return path


def ensure_schema() -> Path:
    return contests.init_schema(contests_db_path())


def upsert_contests(items: list[Contest]) -> None:
    ensure_schema()
    rows: list[dict] = []
    for contest in items:
        rows.append(
            {
                "dk_id": contest.id,
                "sport": contest.sport,
                "name": contest.name,
                "start_date": contest.start_dt.isoformat(sep=" "),
                "draft_group": contest.draft_group,
                "total_prizes": contest.total_prizes,
                "entries": contest.entries,
                "positions_paid": None,
                "entry_fee": contest.entry_fee,
                "entry_count": contest.entry_count,
                "max_entry_count": contest.max_entry_count,
                "completed": 0,
                "status": None,
            }
        )
    contests.upsert_contests(contests_db_path(), rows)


def update_contest_status(
    *,
    dk_id: int,
    positions_paid: int | None | object = _UNSET,
    status: str | None | object = _UNSET,
    completed: int | None | object = _UNSET,
) -> int:
    ensure_schema()
    return contests.update_contest_status(
        contests_db_path(),
        dk_id=dk_id,
        positions_paid=positions_paid,
        status=status,
        completed=completed,
    )
