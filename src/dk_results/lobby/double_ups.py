from collections.abc import Sequence

from dk_results.domain.contest import Contest

from .contest_filter import filter_double_ups


def get_double_ups(
    contests: Sequence[Contest],
    draft_groups: Sequence[int],
    min_entry_fee: int = 5,
    max_entry_fee: int = 50,
    entries: int = 125,
) -> list[Contest]:
    """Filter contests to double-ups matching configured thresholds."""
    return filter_double_ups(
        contests,
        min_entry_fee=min_entry_fee,
        max_entry_fee=max_entry_fee,
        draft_groups=draft_groups,
        min_entries=entries,
    )
