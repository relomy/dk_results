import datetime
import logging
from typing import Any, Type

from dk_results.domain.sport import Sport
from dk_results.lobby.parsing import _parse_start_date, log_draft_group_event

logger = logging.getLogger(__name__)


def _passes_tag(tag: str) -> bool:
    return tag == "Featured"


def get_featured_draft_group_ids(groups: list[dict[str, Any]]) -> set[int]:
    """Return raw draft-group IDs whose tag is exactly ``Featured``."""
    return {group["DraftGroupId"] for group in groups if _passes_tag(group["DraftGroupTag"])}


def _passes_game_type(game_type_id: int, sport: Type[Sport]) -> bool:
    if sport.contest_restraint_game_type_id is None:
        return True
    return game_type_id == sport.contest_restraint_game_type_id


def _passes_suffix(suffix: str | None, sport: Type[Sport]) -> bool:
    if sport.suffixes is None:
        return True
    if suffix is None:
        return not sport.suffixes or None in sport.suffixes
    return any(pattern.search(suffix) for pattern in sport.get_suffix_patterns())


def _passes_time(dt_start: datetime.datetime, sport: Type[Sport]) -> bool:
    if sport.contest_restraint_time is None:
        return True
    return dt_start.time() >= sport.contest_restraint_time


def _deduplicate_showdown(
    entries: list[tuple[datetime.datetime, int, str, str | None, int, int, datetime.datetime]],
    sport: Type[Sport],
) -> list[int]:
    counts: dict[datetime.datetime, int] = {}
    for start_key, *_ in entries:
        counts[start_key] = counts.get(start_key, 0) + 1

    result = []
    for start_key, draft_group_id, tag, suffix, contest_type_id, game_type_id, dt_start in entries:
        if counts[start_key] == 1:
            log_draft_group_event("Append", sport, dt_start, draft_group_id, tag, suffix, contest_type_id, game_type_id)
            result.append(draft_group_id)
        else:
            log_draft_group_event(
                "Skip",
                sport,
                dt_start,
                draft_group_id,
                tag,
                suffix,
                contest_type_id,
                game_type_id,
                level=logging.DEBUG,
                reason="multiple NFLShowdown draft groups at same start time",
            )
    return result


def _normalize_suffix(suffix: str | None) -> str | None:
    if suffix is None:
        return None
    return suffix.strip() or None


def _skipped_suffix_label(suffix: str | None) -> str:
    return suffix if suffix is not None else "<<none>>"


def _suffix_skip_reason(suffix: str | None) -> str:
    return "suffix required" if suffix is None else "suffix mismatch"


def _log_group_skip(
    sport: Type[Sport],
    dt_start: datetime.datetime,
    draft_group_id: int,
    tag: str,
    suffix: str | None,
    contest_type_id: int,
    game_type_id: int,
    reason: str,
) -> None:
    log_draft_group_event(
        "Skip",
        sport,
        dt_start,
        draft_group_id,
        tag,
        suffix,
        contest_type_id,
        game_type_id,
        level=logging.DEBUG,
        reason=reason,
    )


def _process_draft_group(
    group: dict[str, Any],
    sport: Type[Sport],
    is_nfl_showdown: bool,
    result: list[int],
    skipped_suffixes: list[str],
    showdown_entries: list[tuple[datetime.datetime, int, str, str | None, int, int, datetime.datetime]],
) -> None:
    tag = group["DraftGroupTag"]
    suffix = _normalize_suffix(group["ContestStartTimeSuffix"])
    draft_group_id = group["DraftGroupId"]
    contest_type_id = group["ContestTypeId"]
    game_type_id = group["GameTypeId"]

    if not _passes_tag(tag):
        if suffix:
            skipped_suffixes.append(suffix)
        return

    dt_start = _parse_start_date(group["StartDateEst"])

    if not _passes_game_type(game_type_id, sport):
        reason = f"game type constraint (!={sport.contest_restraint_game_type_id}, got {game_type_id})"
        _log_group_skip(sport, dt_start, draft_group_id, tag, suffix, contest_type_id, game_type_id, reason)
        return

    if not _passes_suffix(suffix, sport):
        skipped_suffixes.append(_skipped_suffix_label(suffix))
        reason = _suffix_skip_reason(suffix)
        _log_group_skip(sport, dt_start, draft_group_id, tag, suffix, contest_type_id, game_type_id, reason)
        return

    if not _passes_time(dt_start, sport):
        reason = f"time constraint (<{sport.contest_restraint_time})"
        _log_group_skip(sport, dt_start, draft_group_id, tag, suffix, contest_type_id, game_type_id, reason)
        return

    if is_nfl_showdown:
        start_key = dt_start.replace(second=0, microsecond=0)
        showdown_entries.append((start_key, draft_group_id, tag, suffix, contest_type_id, game_type_id, dt_start))
        return

    log_draft_group_event("Append", sport, dt_start, draft_group_id, tag, suffix, contest_type_id, game_type_id)
    result.append(draft_group_id)


def filter_draft_groups(groups: list[dict[str, Any]], sport: Type[Sport]) -> list[int]:
    """Return qualifying draft-group IDs for the given sport."""
    result: list[int] = []
    skipped_suffixes: list[str] = []
    is_nfl_showdown = sport.name == "NFLShowdown"
    showdown_entries: list[tuple[datetime.datetime, int, str, str | None, int, int, datetime.datetime]] = []

    for group in groups:
        _process_draft_group(group, sport, is_nfl_showdown, result, skipped_suffixes, showdown_entries)

    if skipped_suffixes:
        logger.debug("[%4s] Skipped suffixes [%s]", sport.name, ", ".join(skipped_suffixes))

    if is_nfl_showdown and showdown_entries:
        result.extend(_deduplicate_showdown(showdown_entries, sport))

    return result
