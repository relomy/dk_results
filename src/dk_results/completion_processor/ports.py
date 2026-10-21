"""The completion workflow's ports, config and clock, shared by its modules."""

from __future__ import annotations

import datetime
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from dk_results import discord_announcements

if TYPE_CHECKING:
    from dk_results.domain.sport import Sport

# ``now(tz)``: the current time in ``tz`` (naive wall time for ``None``), like
# ``datetime.datetime.now``. Warning windows and "time left" text read it.
Now = Callable[[datetime.tzinfo | None], datetime.datetime]


def system_now(tz: datetime.tzinfo | None = None) -> datetime.datetime:
    """The default `Now`; resolves ``datetime`` at call time, so tests can freeze it."""
    return datetime.datetime.now(tz)


class PresenceOracle(Protocol):
    """The presence-verdict provider the processor consults for suppression."""

    def verdict(self, dk_id: int, start_date: str, vip_names: list[str]) -> str: ...


@dataclass(frozen=True)
class CompletionProcessorConfig:
    """Presentation and scheduling inputs resolved by the composition root."""

    sport_choices: Mapping[str, type[Sport]]
    warning_schedules: Mapping[str, list[int]]
    default_warning_schedule: list[int]
    sport_emoji: Mapping[str, str]
    spreadsheet_id: str | None
    sheet_gid_map: Mapping[str, int]
    vips: list[str]
    dashboard_base_url: str | None = discord_announcements.DEFAULT_DASHBOARD_BASE_URL
    # Whether milestone announcements may be sent this run. Resolved explicitly
    # at the composition root (from ``DISCORD_NOTIFICATIONS_ENABLED``) and
    # independent of whether a sender is wired: "off" is a deliberate state, so a
    # disabled run still constructs the processor and short-circuits every send.
    notifications_enabled: bool = True
