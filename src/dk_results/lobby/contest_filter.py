import datetime
from collections.abc import Sequence

from dk_results.domain.contest import Contest


def is_double_up_contest(contest: Contest) -> bool:
    return contest.is_double_up and contest.is_guaranteed and contest.max_entry_count == 1


def filter_double_ups(
    contests: Sequence[Contest],
    *,
    min_entry_fee: int,
    max_entry_fee: int,
    start_date: datetime.date | None = None,
    draft_groups: Sequence[int] | None = None,
    min_entries: int = 0,
    game_type_id: int | None = None,
    name_contains: str | None = None,
    name_excludes: str | None = None,
) -> list[Contest]:
    """Filter contests to double-ups satisfying all supplied constraints.

    Fee is expressed as a closed range; for an exact match pass min_entry_fee == max_entry_fee.
    All optional parameters default to no constraint when None / 0.
    """
    draft_group_set = set(draft_groups) if draft_groups is not None else None
    return [
        c
        for c in contests
        if _matches(
            c,
            min_entry_fee,
            max_entry_fee,
            start_date,
            draft_group_set,
            min_entries,
            game_type_id,
            name_contains,
            name_excludes,
        )
    ]


def largest_by_entries(contests: Sequence[Contest]) -> Contest | None:
    """Return the contest with the highest entry count, or None if the list is empty."""
    return max(contests, key=lambda c: c.entries) if contests else None


def _matches(
    contest: Contest,
    min_entry_fee: int,
    max_entry_fee: int,
    start_date: datetime.date | None,
    draft_group_set: set[int] | None,
    min_entries: int,
    game_type_id: int | None,
    name_contains: str | None,
    name_excludes: str | None,
) -> bool:
    name_lower = contest.name.lower()
    return all(
        (
            is_double_up_contest(contest),
            min_entry_fee <= contest.entry_fee <= max_entry_fee,
            start_date is None or contest.start_dt.date() == start_date,
            draft_group_set is None or contest.draft_group in draft_group_set,
            contest.entries >= min_entries,
            game_type_id is None or contest.game_type_id == game_type_id,
            name_contains is None or name_contains.lower() in name_lower,
            name_excludes is None or name_excludes.lower() not in name_lower,
        )
    )
