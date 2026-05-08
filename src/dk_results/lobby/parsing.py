import datetime
import logging
from typing import Any

from dk_results.classes.sport import Sport

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
