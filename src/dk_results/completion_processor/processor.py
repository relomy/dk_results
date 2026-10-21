"""`CompletionProcessor`: builds the workflow's collaborators and runs them in order."""

from __future__ import annotations

import datetime
import logging
from collections.abc import Callable
from typing import TYPE_CHECKING

from dk_results import discord_announcements
from dk_results.completion_processor import messages
from dk_results.completion_processor.announcer import MilestoneAnnouncer
from dk_results.completion_processor.ports import system_now
from dk_results.completion_processor.soft_finish import SoftFinishAnnouncer
from dk_results.completion_processor.sync import ContestSync, fetch_contest_state
from dk_results.completion_processor.warnings import WarningScheduler
from dk_results.persistence.notification_store import NotificationStore

if TYPE_CHECKING:
    from dk_results.completion_processor.ports import CompletionProcessorConfig, Now, PresenceOracle
    from dk_results.notifications.vip_presence import ContestResultsPort
    from dk_results.persistence.contestdatabase import ContestDatabase
    from dk_results.sport_processor import BonusSenderPort

# The package name: log lines keep the `dk_results.completion_processor` logger.
logger = logging.getLogger(__package__)


class CompletionProcessor:
    """
    Coordinates the full contest-completion workflow for one run.

    Construction-time dependencies are injected. ``run(conn)`` performs, in
    order:

      1. warnings   — starting-soon announcements per sport (needs a sender)
      2. sync       — advance each incomplete contest's stored state, and
                      announce live / completed transitions (announce needs a sender)
      3. soft-finish — announce a VIP-cash summary for effectively-final contests

    Idempotent: every announcement is recorded in `NotificationStore` and never
    sent twice. Contest-state sync runs even without a sender.

    ``now(tz)`` is the current time for warning windows and "time left" text;
    ``clock()`` stamps a stored contest update (default: ``now`` in UTC).
    Suppression policy: see `MilestoneAnnouncer`.
    """

    def __init__(
        self,
        *,
        contest_db: ContestDatabase,
        results: ContestResultsPort,
        presence: PresenceOracle | None,
        bonus_sender: BonusSenderPort | None,
        config: CompletionProcessorConfig,
        clock: Callable[[], datetime.datetime] | None = None,
        now: Now = system_now,
    ) -> None:
        self._clock = clock or (lambda: now(datetime.timezone.utc))
        self._db = contest_db
        self._results = results
        self._presence = presence
        self._sender = bonus_sender
        self._config = config
        self._announcer = MilestoneAnnouncer(sender=bonus_sender, presence=presence, config=config, now=now)
        self._warnings = WarningScheduler(contest_db=contest_db, config=config, announcer=self._announcer, now=now)
        self._contest_sync = ContestSync(
            contest_db=contest_db, results=results, config=config, announcer=self._announcer, clock=self._clock
        )
        self._soft_finish = SoftFinishAnnouncer(
            contest_db=contest_db, results=results, config=config, announcer=self._announcer
        )

    def run(self, conn) -> None:
        """Advance and announce every tracked contest's milestones."""
        store = NotificationStore(conn)

        if self._announcing:
            self._warnings.run(store)

        self._sync_and_notify(store)

        if self._announcing:
            self._soft_finish.run(store)

    @property
    def _announcing(self) -> bool:
        """Whether milestone announcements may be sent this run.

        Two independent inputs must both hold: notifications are explicitly
        enabled (``notifications_enabled``) and a sender is wired. Contest-state
        sync runs regardless; only sends are gated.
        """
        return self._config.notifications_enabled and self._sender is not None

    def _sync_and_notify(self, store: NotificationStore) -> None:
        incomplete_contests = self._db.get_incomplete_contests()

        if not incomplete_contests:
            return

        logger.debug("found %i incomplete contests", len(incomplete_contests))

        skip_draft_groups: list[int] = []

        for (
            dk_id,
            draft_group,
            entries,
            positions_paid,
            status,
            completed,
            name,
            start_date,
            sport_name,
        ) in incomplete_contests:
            if ContestSync.should_skip(dk_id, draft_group, positions_paid, name, skip_draft_groups):
                continue

            try:
                contest_data = self._sync_contest(
                    dk_id,
                    draft_group,
                    entries,
                    positions_paid,
                    status,
                    completed,
                    name,
                    start_date,
                    skip_draft_groups,
                )
                if contest_data is not None and self._announcing:
                    self._contest_sync.announce_transitions(
                        store, dk_id, name, start_date, sport_name, status, completed, contest_data
                    )
            except Exception:
                logger.exception("Failed to sync contest dk_id=%s", dk_id)

    def _sync_contest(
        self,
        dk_id: int,
        draft_group: int,
        entries: int,
        positions_paid: int | None,
        status: str,
        completed: int,
        name: str,
        start_date: object,
        skip_draft_groups: list[int],
    ) -> dict | None:
        """One contest's sync step, looked up on the instance so a test can make it fail."""
        return self._contest_sync.sync(
            dk_id, draft_group, entries, positions_paid, status, completed, name, start_date, skip_draft_groups
        )

    # ── Delegates kept for tests/test_completion_processor.py ───────────────

    def _get_contest_data(self, dk_id) -> dict | None:
        return fetch_contest_state(self._results, dk_id)

    def _sport_emoji(self, sport_name: str) -> str:
        return discord_announcements.sport_emoji(sport_name, self._config.sport_emoji)

    def _sheet_link(self, sheet_title: str) -> str | None:
        return messages.sheet_link(self._config, sheet_title)

    def _format_contest_announcement(
        self, prefix: str, sport_name: str, contest_name: str, start_date: str, dk_id: int
    ) -> str:
        return self._announcer.format_milestone(prefix, sport_name, contest_name, start_date, dk_id)
