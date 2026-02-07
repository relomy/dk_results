import datetime
import logging
from typing import Any, Type

from classes.sport import Sport

logger = logging.getLogger(__name__)


def get_contests_from_response(
    response: dict[str, Any] | list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Extract contests list from DraftKings lobby response."""
    if isinstance(response, list):
        return response
    if "Contests" in response:
        return response["Contests"]
    logger.error("response isn't a dict or a list??? exiting")
    raise SystemExit()


def log_draft_group_event(
    action: str,
    sport_obj: Sport | Type[Sport],
    start_date: datetime.datetime,
    draft_group_id: int,
    tag: str,
    suffix: str | None,
    contest_type_id: int,
    game_type_id: int,
    *,
    level: int = logging.INFO,
    reason: str | None = None,
) -> None:
    """Log a draft-group append/skip action with stable formatting."""
    message = "[%4s] %s: start date: [%s] dg/tag/suffix/typid/gameid: [%d]/[%s]/[%s]/[%d]/[%d]"
    args: tuple[Any, ...] = (
        sport_obj.name,
        action,
        start_date,
        draft_group_id,
        tag,
        suffix,
        contest_type_id,
        game_type_id,
    )
    if reason:
        message += " reason: %s"
        args = args + (reason,)
    logger.log(level, message, *args)


def _parse_start_date(start_date_est: str) -> datetime.datetime:
    return datetime.datetime.fromisoformat(start_date_est[:-8])


def get_draft_groups_from_response(
    response: dict[str, Any], sport_obj: Type[Sport]
) -> list[int]:
    """Extract allowed draft-group ids from lobby response."""
    response_draft_groups: list[int] = []
    skipped_dg_suffixes: list[str] = []
    suffix_patterns = sport_obj.get_suffix_patterns()
    allow_suffixless = sport_obj.allow_suffixless_draft_groups
    is_nfl_showdown = sport_obj.name == "NFLShowdown"
    showdown_entries: list[
        tuple[datetime.datetime, int, str, str | None, int, int, datetime.datetime]
    ] = []

    for draft_group in response["DraftGroups"]:
        tag = draft_group["DraftGroupTag"]
        suffix = draft_group["ContestStartTimeSuffix"]
        draft_group_id = draft_group["DraftGroupId"]
        start_date_est = draft_group["StartDateEst"]
        contest_type_id = draft_group["ContestTypeId"]
        game_type_id = draft_group["GameTypeId"]

        if suffix is not None:
            suffix = suffix.strip() or None

        if tag != "Featured":
            if suffix:
                skipped_dg_suffixes.append(suffix)
            continue

        dt_start_date = _parse_start_date(start_date_est)

        if (
            sport_obj.contest_restraint_game_type_id is not None
            and game_type_id != sport_obj.contest_restraint_game_type_id
        ):
            log_draft_group_event(
                "Skip",
                sport_obj,
                dt_start_date,
                draft_group_id,
                tag,
                suffix,
                contest_type_id,
                game_type_id,
                level=logging.DEBUG,
                reason=(
                    "game type constraint "
                    f"(!={sport_obj.contest_restraint_game_type_id}, got {game_type_id})"
                ),
            )
            continue

        if suffix is None:
            if not allow_suffixless:
                log_draft_group_event(
                    "Skip",
                    sport_obj,
                    dt_start_date,
                    draft_group_id,
                    tag,
                    suffix,
                    contest_type_id,
                    game_type_id,
                    level=logging.DEBUG,
                    reason="suffix required",
                )
                skipped_dg_suffixes.append("<<none>>")
                continue

            log_draft_group_event(
                "Append",
                sport_obj,
                dt_start_date,
                draft_group_id,
                tag,
                suffix,
                contest_type_id,
                game_type_id,
            )
            response_draft_groups.append(draft_group_id)
            continue

        matches_suffix = False
        if suffix_patterns:
            matches_suffix = any(pattern.search(suffix) for pattern in suffix_patterns)

        if not matches_suffix:
            skipped_dg_suffixes.append(suffix)
            log_draft_group_event(
                "Skip",
                sport_obj,
                dt_start_date,
                draft_group_id,
                tag,
                suffix,
                contest_type_id,
                game_type_id,
                level=logging.DEBUG,
                reason="suffix mismatch",
            )
            continue

        if (
            sport_obj.contest_restraint_time
            and dt_start_date.time() < sport_obj.contest_restraint_time
        ):
            log_draft_group_event(
                "Skip",
                sport_obj,
                dt_start_date,
                draft_group_id,
                tag,
                suffix,
                contest_type_id,
                game_type_id,
                level=logging.DEBUG,
                reason=f"time constraint (<{sport_obj.contest_restraint_time})",
            )
            continue

        if is_nfl_showdown:
            start_key = dt_start_date.replace(second=0, microsecond=0)
            showdown_entries.append(
                (
                    start_key,
                    draft_group_id,
                    tag,
                    suffix,
                    contest_type_id,
                    game_type_id,
                    dt_start_date,
                )
            )
            continue

        log_draft_group_event(
            "Append",
            sport_obj,
            dt_start_date,
            draft_group_id,
            tag,
            suffix,
            contest_type_id,
            game_type_id,
        )
        response_draft_groups.append(draft_group_id)

    if skipped_dg_suffixes:
        logger.debug(
            "[%4s] Skipped suffixes [%s]",
            sport_obj.name,
            ", ".join(skipped_dg_suffixes),
        )

    if is_nfl_showdown and showdown_entries:
        showdown_counts: dict[datetime.datetime, int] = {}
        for start_key, *_ in showdown_entries:
            showdown_counts[start_key] = showdown_counts.get(start_key, 0) + 1

        for (
            start_key,
            draft_group_id,
            tag,
            suffix,
            contest_type_id,
            game_type_id,
            dt_start_date,
        ) in showdown_entries:
            if showdown_counts[start_key] == 1:
                log_draft_group_event(
                    "Append",
                    sport_obj,
                    dt_start_date,
                    draft_group_id,
                    tag,
                    suffix,
                    contest_type_id,
                    game_type_id,
                )
                response_draft_groups.append(draft_group_id)
            else:
                log_draft_group_event(
                    "Skip",
                    sport_obj,
                    dt_start_date,
                    draft_group_id,
                    tag,
                    suffix,
                    contest_type_id,
                    game_type_id,
                    level=logging.DEBUG,
                    reason="multiple NFLShowdown draft groups at same start time",
                )

    return response_draft_groups


def build_draft_group_start_map(
    draft_groups: list[dict[str, Any]], allowed_ids: set[int]
) -> dict[int, datetime.datetime]:
    """Map allowed draft-group ids to parsed start datetimes."""
    if not draft_groups or not allowed_ids:
        return {}

    start_map: dict[int, datetime.datetime] = {}
    for draft_group in draft_groups:
        draft_group_id = draft_group.get("DraftGroupId")
        if draft_group_id is None or draft_group_id not in allowed_ids:
            continue

        start_date_est = draft_group.get("StartDateEst")
        if not start_date_est:
            continue

        try:
            start_map[draft_group_id] = _parse_start_date(start_date_est)
        except (TypeError, ValueError):
            logger.debug(
                "invalid StartDateEst for dg_id=%s: %s",
                draft_group_id,
                start_date_est,
            )

    return start_map
