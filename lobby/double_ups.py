from collections.abc import Sequence
from typing import Any

from classes.contest import Contest


def contest_meets_criteria(contest: Contest, criteria: dict[str, Any]) -> bool:
    """Check if contest matches base double-up criteria."""
    return (
        contest.entries >= criteria["entries"]
        and contest.draft_group in criteria["draft_groups"]
        and contest.entry_fee >= criteria["min_entry_fee"]
        and contest.entry_fee <= criteria["max_entry_fee"]
        and contest.max_entry_count == 1
        and contest.is_guaranteed
        and contest.is_double_up
    )


def get_double_ups(
    contests: Sequence[Contest],
    draft_groups: Sequence[int],
    min_entry_fee: int = 5,
    max_entry_fee: int = 50,
    entries: int = 125,
) -> list[Contest]:
    """Filter contests to double-ups matching configured thresholds."""
    criteria: dict[str, Any] = {
        "draft_groups": draft_groups,
        "min_entry_fee": min_entry_fee,
        "max_entry_fee": max_entry_fee,
        "entries": entries,
    }
    return [contest for contest in contests if contest_meets_criteria(contest, criteria)]


def get_stats(contests: Sequence[Contest], *, include_largest: bool = False) -> dict[str, Any]:
    """Build per-date contest stats used by find_new_double_ups and dkcontests."""
    stats: dict[str, Any] = {}
    for contest in contests:
        start_date = contest.start_dt.strftime("%Y-%m-%d")
        if start_date not in stats:
            stats[start_date] = {"count": 0}
        stats[start_date]["count"] += 1

        if (
            contest.max_entry_count == 1
            and contest.is_guaranteed
            and contest.is_double_up
        ):
            if "dubs" not in stats[start_date]:
                stats[start_date]["dubs"] = {}

            if contest.entry_fee not in stats[start_date]["dubs"]:
                stats[start_date]["dubs"][contest.entry_fee] = (
                    {"count": 0, "largest": 0}
                    if include_largest
                    else 0
                )

            if include_largest:
                stats[start_date]["dubs"][contest.entry_fee]["count"] += 1
                if contest.entries > stats[start_date]["dubs"][contest.entry_fee]["largest"]:
                    stats[start_date]["dubs"][contest.entry_fee]["largest"] = contest.entries
            else:
                stats[start_date]["dubs"][contest.entry_fee] += 1

    return stats
