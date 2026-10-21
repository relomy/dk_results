"""Starting-soon warnings: the completion workflow's first milestone.

`WarningScheduler.run(store)` takes each sport's next upcoming contest and
announces every entry of its warning schedule (minutes before start) whose
window the contest is now inside. The run is a cron job every 10 minutes, so a
warning fires while ``now < start <= now + minutes`` rather than at an exact
time; `NotificationStore` keeps each ``warning:<minutes>`` to one send.
"""

from __future__ import annotations

import datetime
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from dk_results.completion_processor.messages import _parse_start_date

if TYPE_CHECKING:
    from dk_results.completion_processor.announcer import MilestoneAnnouncer
    from dk_results.completion_processor.ports import CompletionProcessorConfig, Now
    from dk_results.domain.sport import Sport
    from dk_results.persistence.contestdatabase import ContestDatabase
    from dk_results.persistence.notification_store import NotificationStore

# The package name: log lines keep the `dk_results.completion_processor` logger.
logger = logging.getLogger(__package__)


@dataclass(frozen=True)
class _UpcomingContest:
    """The one upcoming-contest row a sport's warning schedule is evaluated against."""

    sport_cls: type[Sport]
    dk_id: int
    name: str
    start_date: str
    start_dt: datetime.datetime
    now: datetime.datetime


class WarningScheduler:
    """Announces each sport's due starting-soon warnings (needs a sender)."""

    def __init__(
        self,
        *,
        contest_db: ContestDatabase,
        config: CompletionProcessorConfig,
        announcer: MilestoneAnnouncer,
        now: Now,
    ) -> None:
        self._db = contest_db
        self._config = config
        self._announcer = announcer
        self._now = now

    def run(self, store: NotificationStore) -> None:
        logged_schedules: set[str] = set()
        for sport_cls in self._config.sport_choices.values():
            upcoming_match = self._db.get_next_upcoming_contest(
                sport_cls.name,
                sport_cls.sheet_min_entry_fee,
                sport_cls.keyword,
            )
            upcoming_any = self._db.get_next_upcoming_contest_any(sport_cls.name)
            row = upcoming_match or upcoming_any
            if not row:
                continue
            dk_id, name, _draft_group, _positions_paid, start_date = row
            start_dt = _parse_start_date(start_date)
            if not start_dt:
                continue
            now = self._now(start_dt.tzinfo)
            # This script runs every 10 minutes via cron, so warnings use windows
            # rather than requiring an exact timestamp match.
            contest = _UpcomingContest(
                sport_cls=sport_cls, dk_id=dk_id, name=name, start_date=start_date, start_dt=start_dt, now=now
            )
            schedule = self._warning_schedule_for(sport_cls.name)
            self._log_schedule_once(sport_cls.name, schedule, sport_cls.name.lower(), logged_schedules)
            for warning_minutes in schedule:
                self._maybe_announce_warning(store, contest, warning_minutes)

    def _warning_schedule_for(self, sport_name: str) -> list[int]:
        """Return the warning schedule for a sport, falling back to the default."""
        key = sport_name.lower()
        schedules = self._config.warning_schedules
        return schedules.get(key) or schedules.get("default", self._config.default_warning_schedule)

    def _log_schedule_once(
        self, sport_name: str, schedule: list[int], schedule_key: str, logged_schedules: set[str]
    ) -> None:
        if schedule_key in logged_schedules:
            return
        source = "sport" if schedule_key in self._config.warning_schedules else "default"
        logger.debug("warning schedule for %s: %s (source=%s)", sport_name, schedule, source)
        logged_schedules.add(schedule_key)

    def _maybe_announce_warning(
        self,
        store: NotificationStore,
        contest: _UpcomingContest,
        warning_minutes: int,
    ) -> None:
        if not (contest.now < contest.start_dt <= contest.now + datetime.timedelta(minutes=warning_minutes)):
            return
        warning_key = f"warning:{warning_minutes}"
        if store.has_notification(contest.dk_id, warning_key):
            logger.debug(
                "warning already sent for %s dk_id=%s (%sm)", contest.sport_cls.name, contest.dk_id, warning_minutes
            )
            return
        self._announcer.announce(
            store,
            require_confirmed_vip=True,
            kind=warning_key,
            prefix=f"Contest starting soon ({warning_minutes}m)",
            sport_name=contest.sport_cls.name,
            contest_name=contest.name,
            start_date=str(contest.start_date),
            dk_id=contest.dk_id,
            log_label="warning",
            log_suffix=f" ({warning_minutes}m)",
        )
