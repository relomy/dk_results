import datetime
import logging
from typing import Any, Type

from dk_results.classes.sport import Sport
from dk_results.lobby.parsing import _parse_start_date, log_draft_group_event

logger = logging.getLogger(__name__)


def _passes_tag(tag: str) -> bool:
    return tag == "Featured"


def _passes_game_type(game_type_id: int, sport: Type[Sport]) -> bool:
    if sport.contest_restraint_game_type_id is None:
        return True
    return game_type_id == sport.contest_restraint_game_type_id


def _passes_suffix(suffix: str | None, sport: Type[Sport]) -> bool:
    if suffix is None:
        return sport.allow_suffixless_draft_groups
    suffix_patterns = sport.get_suffix_patterns()
    if not suffix_patterns:
        return True
    return any(pattern.search(suffix) for pattern in suffix_patterns)


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


def filter_draft_groups(groups: list[dict[str, Any]], sport: Type[Sport]) -> list[int]:
    """Return qualifying draft-group IDs for the given sport."""
    result: list[int] = []
    skipped_suffixes: list[str] = []
    is_nfl_showdown = sport.name == "NFLShowdown"
    showdown_entries: list[tuple[datetime.datetime, int, str, str | None, int, int, datetime.datetime]] = []

    for group in groups:
        tag = group["DraftGroupTag"]
        suffix = group["ContestStartTimeSuffix"]
        draft_group_id = group["DraftGroupId"]
        start_date_est = group["StartDateEst"]
        contest_type_id = group["ContestTypeId"]
        game_type_id = group["GameTypeId"]

        if suffix is not None:
            suffix = suffix.strip() or None

        if not _passes_tag(tag):
            if suffix:
                skipped_suffixes.append(suffix)
            continue

        dt_start = _parse_start_date(start_date_est)

        if not _passes_game_type(game_type_id, sport):
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
                reason=f"game type constraint (!={sport.contest_restraint_game_type_id}, got {game_type_id})",
            )
            continue

        if not _passes_suffix(suffix, sport):
            skipped_suffixes.append(suffix if suffix is not None else "<<none>>")
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
                reason="suffix required" if suffix is None else "suffix mismatch",
            )
            continue

        if not _passes_time(dt_start, sport):
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
                reason=f"time constraint (<{sport.contest_restraint_time})",
            )
            continue

        if is_nfl_showdown:
            start_key = dt_start.replace(second=0, microsecond=0)
            showdown_entries.append((start_key, draft_group_id, tag, suffix, contest_type_id, game_type_id, dt_start))
            continue

        log_draft_group_event("Append", sport, dt_start, draft_group_id, tag, suffix, contest_type_id, game_type_id)
        result.append(draft_group_id)

    if skipped_suffixes:
        logger.debug("[%4s] Skipped suffixes [%s]", sport.name, ", ".join(skipped_suffixes))

    if is_nfl_showdown and showdown_entries:
        result.extend(_deduplicate_showdown(showdown_entries, sport))

    return result
