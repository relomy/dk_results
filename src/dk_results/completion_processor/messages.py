"""Milestone message text: ADR-0010's shared builder bound to this run's config.

Pure functions of the config, the milestone facts and a `Now` clock (for the
"time left" text).
"""

from __future__ import annotations

import datetime
from typing import TYPE_CHECKING, Any

from dk_results import discord_announcements

if TYPE_CHECKING:
    from dk_results.completion_processor.ports import CompletionProcessorConfig, Now


def _parse_start_date(start_date: Any) -> datetime.datetime | None:
    if not start_date:
        return None
    if isinstance(start_date, datetime.datetime):
        return start_date
    try:
        return datetime.datetime.fromisoformat(str(start_date))
    except (TypeError, ValueError):
        return None


def relative_time(start_date: str, now: Now) -> str | None:
    """Time left until ``start_date`` ("13m"), or ``None`` once it has passed."""
    start_dt = _parse_start_date(start_date)
    if not start_dt:
        return None
    delta = start_dt - now(start_dt.tzinfo)
    if delta.total_seconds() <= 0:
        return None
    return discord_announcements.relative_time_from_seconds(int(delta.total_seconds()))


def sheet_link(config: CompletionProcessorConfig, sheet_title: str) -> str | None:
    return discord_announcements.sheet_link(config.spreadsheet_id, config.sheet_gid_map, sheet_title)


def format_milestone(
    config: CompletionProcessorConfig,
    now: Now,
    *,
    prefix: str,
    sport_name: str,
    contest_name: str,
    start_date: str,
    dk_id: int,
) -> str:
    """The warning / live / completed message."""
    return discord_announcements.build_milestone_announcement(
        prefix=prefix,
        sport_name=sport_name,
        contest_name=contest_name,
        start_date=start_date,
        dk_id=dk_id,
        relative_time=relative_time(start_date, now),
        sheet_link_url=sheet_link(config, sport_name),
        dashboard_base_url=config.dashboard_base_url,
        emoji_map=config.sport_emoji,
    )


def format_soft_finish(
    config: CompletionProcessorConfig,
    now: Now,
    *,
    sport_name: str,
    contest_name: str,
    start_date: str,
    dk_id: int,
    top_score: str,
    cashing_score: str,
    vips_cashed: list[str],
    is_update: bool,
) -> str:
    """The soft-finish summary, marked "(updated)" when ``is_update``."""
    return discord_announcements.build_soft_finish_announcement(
        sport_name=sport_name,
        contest_name=contest_name,
        start_date=start_date,
        dk_id=dk_id,
        top_score=top_score,
        cashing_score=cashing_score,
        vips_cashed=vips_cashed,
        is_update=is_update,
        relative_time=relative_time(start_date, now),
        sheet_link_url=sheet_link(config, sport_name),
        dashboard_base_url=config.dashboard_base_url,
        emoji_map=config.sport_emoji,
    )
