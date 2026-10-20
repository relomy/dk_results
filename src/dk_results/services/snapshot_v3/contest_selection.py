"""Contest selection for the snapshot collector: the pure half.

The selection reason and candidate summary, the ``ContestRow`` built from a
DraftKings contest detail when the DB misses, the normalized contest state and
its ``completed_at`` guard. The collector does the DB and DraftKings reads.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from dk_results.persistence.contestdatabase import ContestRow
from dk_results.services.snapshot_v3.normalize import to_utc_iso

CANDIDATE_LIMIT = 5


def _build_selection_reason(
    *,
    mode: str,
    sport: str,
    min_entry_fee: int,
    keyword: str,
    selected_from_candidate_count: int,
    contest_id: int | None = None,
) -> dict[str, Any]:
    criteria: dict[str, Any] = {
        "sport": sport,
        "min_entry_fee": min_entry_fee,
        "keyword": keyword,
        "status_window": "start_date <= now && completed=0",
        "primary_preference": "entry_fee >= min_entry_fee then fallback below min",
    }
    if mode == "explicit_id":
        criteria = {"contest_id": str(contest_id) if contest_id is not None else None}

    return {
        "mode": mode,
        "criteria": criteria,
        "tie_breakers": [
            "entry_fee desc",
            "entries desc",
            "start_date desc",
            "dk_id desc",
        ],
        "selected_from_candidate_count": selected_from_candidate_count,
    }


def _summarize_candidates(rows: list[tuple], top_n: int = CANDIDATE_LIMIT) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for row in rows:
        contest_id, name, entry_fee, start_date, entries, selection_priority = row
        normalized.append(
            {
                "contest_id": str(contest_id),
                "name": name,
                "entry_fee": entry_fee,
                "entries": entries,
                "start_time_utc": to_utc_iso(start_date),
                "selection_priority": int(selection_priority),
            }
        )

    normalized.sort(
        key=lambda item: (
            item["selection_priority"],
            -int(item["entry_fee"] or 0),
            -int(item["entries"] or 0),
            item["contest_id"],
        )
    )
    return normalized[:top_n]


def _first_not_blank(*values: Any) -> Any:
    for value in values:
        if value not in (None, ""):
            return value
    return None


def _contest_row_from_detail(dk_id: int, detail: dict[str, Any]) -> ContestRow:
    contest_detail = detail.get("contestDetail", {})
    payout_summary = contest_detail.get("payoutSummary") or []
    positions_paid = None
    if payout_summary:
        positions_paid = payout_summary[0].get("maxPosition")
    start_time = contest_detail.get("contestStartTime")
    prize_pool = _first_not_blank(
        contest_detail.get("totalPrizePool"),
        contest_detail.get("totalPrizes"),
        contest_detail.get("totalPayouts"),
        contest_detail.get("totalPayout"),
        contest_detail.get("prizePool"),
        contest_detail.get("payout"),
    )
    max_entries_per_user = _first_not_blank(
        contest_detail.get("maxEntriesPerUser"),
        contest_detail.get("maximumEntriesPerUser"),
        contest_detail.get("maxEntriesPerPerson"),
        contest_detail.get("maxEntryCount"),
    )
    return ContestRow(
        dk_id=dk_id,
        name=contest_detail.get("name"),
        draft_group=contest_detail.get("draftGroupId"),
        positions_paid=positions_paid,
        start_date=start_time,
        entry_fee=contest_detail.get("entryFee"),
        entries=contest_detail.get("maximumEntries"),
        contest_state=contest_detail.get("contestState") or contest_detail.get("contestStatus"),
        contest_completed=contest_detail.get("isCompleted"),
        prize_pool=prize_pool,
        max_entries_per_user=max_entries_per_user,
    )


def _normalize_contest_state(raw_state: Any, completed: Any) -> str | None:
    if completed in (1, True, "1", "true", "True"):
        return "completed"
    text = str(raw_state or "").strip().lower()
    if not text:
        return None
    if text in {"live", "in progress", "in_progress", "started"}:
        return "live"
    if text in {"completed", "complete", "final"}:
        return "completed"
    if text in {"cancelled", "canceled"}:
        return "cancelled"
    if text in {"scheduled", "upcoming", "open"}:
        return "upcoming"
    return None


def _completed_at_for(resolved: _ResolvedContest, state: str | None) -> str | None:
    """The stored ``completed_at``, only for a genuinely completed (never cancelled) contest.

    ``update_contest`` never stamps ``CANCELLED``; this guard is defence in depth against a
    hand-edited database. ``state`` alone cannot exclude cancelled contests, because they
    carry ``completed=1`` and normalise to ``"completed"``.
    """
    cancelled = str(resolved.contest_state or "").strip().lower() in {"cancelled", "canceled"}
    return None if state != "completed" or cancelled else resolved.completed_at


@dataclass(frozen=True)
class _ResolvedContest:
    """Contest identity and metadata resolved from the DB (and DK detail fallback)."""

    mode: str
    candidate_rows: list[tuple]
    dk_id: Any
    contest_name: Any
    draft_group: Any
    positions_paid: Any
    start_date: Any
    entry_fee: Any
    contest_state: Any
    contest_completed: Any
    prize_pool: Any
    max_entries: Any
    max_entries_per_user: Any
    completed_at: str | None = None
