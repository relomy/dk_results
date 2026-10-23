"""`CompletionProcessor`: builds the workflow's collaborators and runs them in order."""

from __future__ import annotations

import datetime
from collections.abc import Callable
from typing import TYPE_CHECKING

from dk_results.completion_processor.announcer import MilestoneAnnouncer
from dk_results.completion_processor.soft_finish import SoftFinishAnnouncer
from dk_results.completion_processor.sync import ContestSync
from dk_results.completion_processor.warnings import WarningScheduler
from dk_results.persistence.notification_store import NotificationStore

if TYPE_CHECKING:
    from dk_results.completion_processor.ports import CompletionProcessorConfig, Now, PresenceOracle
    from dk_results.notifications.vip_presence import ContestResultsPort
    from dk_results.persistence.contestdatabase import ContestDatabase
    from dk_results.sport_processor import BonusSenderPort


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
        now: Now = datetime.datetime.now,
    ) -> None:
        self._clock = clock or (lambda: now(datetime.timezone.utc))
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

        self._contest_sync.run(store, announce=self._announcing)

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
