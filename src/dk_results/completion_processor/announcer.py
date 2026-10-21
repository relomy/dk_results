"""Milestone sends: the suppression policy, then send and record.

`MilestoneAnnouncer` owns everything between "this milestone is due" and "it is
in Discord and in `NotificationStore`": which presence verdict suppresses the
send (ADR-0008), the message (`messages`), the send and the record. Callers keep
the "already announced?" gate, whose wording differs per milestone.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from dk_results.completion_processor import messages
from dk_results.notifications.vip_presence import VIP_ABSENT, VIP_PRESENT, VIP_UNKNOWN_CAPPED

if TYPE_CHECKING:
    from dk_results.completion_processor.ports import CompletionProcessorConfig, Now, PresenceOracle
    from dk_results.persistence.notification_store import NotificationStore
    from dk_results.sport_processor import BonusSenderPort

# The package name: log lines keep the `dk_results.completion_processor` logger.
logger = logging.getLogger(__package__)


class MilestoneAnnouncer:
    """Presence-gated, recorded sends for one run's milestones.

    Suppression policy: warning and live require a confirmed VIP
    (``require_confirmed_vip=True``, see `_presence_blocks_start`); completed
    and soft-finish suppress only on ``absent`` (see `presence_absent`).
    """

    def __init__(
        self,
        *,
        sender: BonusSenderPort | None,
        presence: PresenceOracle | None,
        config: CompletionProcessorConfig,
        now: Now,
    ) -> None:
        self._sender = sender
        self._presence = presence
        self._config = config
        self._now = now

    # ── Suppression policy ──────────────────────────────────────────────────

    def presence_absent(self, dk_id: int, start_date: str) -> bool:
        """Whether presence is ``absent`` (suppress); ``unknown`` allows the send.

        The original, looser policy — still used by completed and soft-finish.
        """
        if self._presence is None:
            return False
        return self._presence.verdict(dk_id, start_date, self._config.vips) == VIP_ABSENT

    def _presence_blocks_start(self, dk_id: int, start_date: str) -> bool:
        """Stricter gate for warning/live: require a confirmed VIP to announce.

        Only ``present`` and ``unknown_capped`` (a field too large to fully
        scan — structural, not a resolved verdict) let the send through.
        ``absent`` and any other ``unknown`` suppress, with no retry: a later,
        independent check (e.g. the next warning-schedule entry) gets its own
        fresh verdict, but nothing here holds a contest in limbo waiting for
        one.
        """
        if self._presence is None:
            return False
        verdict = self._presence.verdict(dk_id, start_date, self._config.vips)
        return verdict not in (VIP_PRESENT, VIP_UNKNOWN_CAPPED)

    # ── Sends ───────────────────────────────────────────────────────────────

    def announce(
        self,
        store: NotificationStore,
        *,
        require_confirmed_vip: bool,
        kind: str,
        prefix: str,
        sport_name: str,
        contest_name: str,
        start_date: str,
        dk_id: int,
        log_label: str,
        log_suffix: str = "",
    ) -> None:
        """Presence-gated send + record of one warning, live or completed milestone.

        ``require_confirmed_vip`` picks the policy: warning/live pass ``True``,
        completed passes ``False``. A suppressed send records nothing.
        """
        assert self._sender is not None
        suppresses = self._presence_blocks_start if require_confirmed_vip else self.presence_absent
        if suppresses(dk_id, start_date):
            logger.info(
                "skipping %s notification for %s dk_id=%s%s; vip_presence suppressed",
                log_label,
                sport_name,
                dk_id,
                log_suffix,
            )
            return
        message = self.format_milestone(prefix, sport_name, contest_name, start_date, dk_id)
        logger.info("sending %s notification for %s dk_id=%s%s", log_label, sport_name, dk_id, log_suffix)
        self._sender.send_message(message)
        store.record_notification(dk_id, kind)
        logger.info("%s notification stored for %s dk_id=%s%s", log_label, sport_name, dk_id, log_suffix)

    def announce_soft_finish(
        self,
        store: NotificationStore,
        *,
        event_key: str,
        sport_name: str,
        contest_name: str,
        start_date: str,
        dk_id: int,
        top_score: str,
        cashing_score: str,
        vips_cashed: list[str],
    ) -> None:
        """Send + record one soft-finish summary, marked "(updated)" after the first."""
        assert self._sender is not None
        message = messages.format_soft_finish(
            self._config,
            self._now,
            sport_name=sport_name,
            contest_name=contest_name,
            start_date=start_date,
            dk_id=dk_id,
            top_score=top_score,
            cashing_score=cashing_score,
            vips_cashed=vips_cashed,
            is_update=store.has_any_soft_finish_notification(dk_id),
        )
        self._sender.send_message(message)
        store.record_notification(dk_id, event_key)

    def format_milestone(self, prefix: str, sport_name: str, contest_name: str, start_date: str, dk_id: int) -> str:
        return messages.format_milestone(
            self._config,
            self._now,
            prefix=prefix,
            sport_name=sport_name,
            contest_name=contest_name,
            start_date=start_date,
            dk_id=dk_id,
        )
