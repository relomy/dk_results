"""Contest-state sync: one contest's DraftKings state, written back when it changed.

`fetch_contest_state` reads a contest's detail through `ContestResultsPort` and
normalizes it to ``{"completed", "status", "entries", "positions_paid"}`` (or
``None`` when the read fails or the contest is not live or finished).
`ContestSync` compares that with the stored row and updates it, tells the run
loop which draft groups need no further fetch this run, and announces a
contest's live / completed transition.
"""

from __future__ import annotations

import datetime
import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from dk_results.completion_processor.announcer import MilestoneAnnouncer
    from dk_results.completion_processor.ports import CompletionProcessorConfig
    from dk_results.notifications.vip_presence import ContestResultsPort
    from dk_results.persistence.contestdatabase import ContestDatabase
    from dk_results.persistence.notification_store import NotificationStore

# The package name: log lines keep the `dk_results.completion_processor` logger.
logger = logging.getLogger(__package__)

COMPLETED_STATUSES = ("COMPLETED", "CANCELLED")


def fetch_contest_state(results: ContestResultsPort, dk_id) -> dict | None:
    try:
        response_json = results.get_contest_detail(dk_id)
        cd = response_json["contestDetail"]
        payout_summary = cd["payoutSummary"]

        positions_paid = payout_summary[0]["maxPosition"]
        status = cd["contestStateDetail"]
        entries = cd["maximumEntries"]

        status = status.upper()

        if status in ["COMPLETED", "LIVE", "CANCELLED"]:
            # set completed status
            completed = 1 if status in COMPLETED_STATUSES else 0
            return {
                "completed": completed,
                "status": status,
                "entries": entries,
                "positions_paid": positions_paid,
            }
    except ValueError as val_err:
        logger.error("JSON decoding error: %s", val_err)
    except KeyError as key_err:
        logger.error("Key error: %s", key_err)
    except Exception:
        logger.exception("Request error")

    return None


class ContestSync:
    """Advances stored contest rows to their DraftKings state and announces live / completed."""

    def __init__(
        self,
        *,
        contest_db: ContestDatabase,
        results: ContestResultsPort,
        config: CompletionProcessorConfig,
        announcer: MilestoneAnnouncer,
        clock: Callable[[], datetime.datetime],
    ) -> None:
        self._db = contest_db
        self._results = results
        self._config = config
        self._announcer = announcer
        self._clock = clock

    @staticmethod
    def should_skip(
        dk_id: int, draft_group: int, positions_paid: int | None, name: str, skip_draft_groups: list[int]
    ) -> bool:
        """Whether an earlier unchanged contest of this draft group already covers this one."""
        if positions_paid is None or draft_group not in skip_draft_groups:
            return False
        logger.debug("dk_id: %s positions_paid: %s", dk_id, positions_paid)
        logger.debug(
            "skipping %s because we've already updated %d [skipped draft groups %s]",
            name,
            draft_group,
            " ".join(str(dg) for dg in skip_draft_groups),
        )
        return True

    def sync(
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
        """Fetch one contest's state and store it if changed; an unchanged contest skips its draft group."""
        logger.debug(
            "getting contest data for %s [id: %i start: %s dg: %d]",
            name,
            dk_id,
            start_date,
            draft_group,
        )
        contest_data = fetch_contest_state(self._results, dk_id)
        if contest_data is None:
            return None
        logger.debug(
            "existing: status: %s entries: %s positions_paid: %s",
            status,
            entries,
            positions_paid,
        )
        logger.debug(
            "contest_fetched dk_id=%s status=%s completed=%s positions_paid=%s",
            dk_id,
            contest_data["status"],
            contest_data["completed"],
            contest_data["positions_paid"],
        )
        new_status = contest_data["status"]
        new_completed = contest_data["completed"]
        if positions_paid != contest_data["positions_paid"] or status != new_status or completed != new_completed:
            self._db.update_contest(
                dk_id,
                positions_paid=contest_data["positions_paid"],
                status=new_status,
                completed=new_completed,
                now=self._clock(),
            )
        else:
            skip_draft_groups.append(draft_group)
            logger.debug("contest data is the same, not updating")
        return contest_data

    # ── Live / completed transitions ────────────────────────────────────────

    def announce_transitions(
        self,
        store: NotificationStore,
        dk_id: int,
        name: str,
        start_date: object,
        sport_name: str,
        status: str,
        completed: int,
        contest_data: dict[str, Any],
    ) -> None:
        """Announce a synced contest's new live (primary contest only) or completed state (needs a sender)."""
        sport_choices = self._config.sport_choices
        if sport_name not in sport_choices:
            return
        new_status = contest_data["status"]
        new_completed = contest_data["completed"]
        if self._is_new_primary_live(sport_choices[sport_name], dk_id, status, new_status):
            self._announce_live(store, dk_id, name, start_date, sport_name)
        if self._is_new_completed(status, new_status, completed, new_completed):
            self._announce_completed(store, dk_id, name, start_date, sport_name)

    def _is_new_primary_live(self, sport_cls, dk_id, status, new_status) -> bool:
        live_row = self._db.get_live_contest(sport_cls.name, sport_cls.sheet_min_entry_fee, sport_cls.keyword)
        return status != "LIVE" and new_status == "LIVE" and bool(live_row and live_row[0] == dk_id)

    @staticmethod
    def _is_new_completed(status, new_status, completed, new_completed) -> bool:
        return (status not in COMPLETED_STATUSES and new_status in COMPLETED_STATUSES) or (
            completed == 0 and new_completed == 1
        )

    def _announce_live(self, store, dk_id, name, start_date, sport_name) -> None:
        logger.info("live transition detected for %s dk_id=%s", sport_name, dk_id)
        if store.has_notification(dk_id, "live"):
            logger.info("live notification already sent for %s dk_id=%s", sport_name, dk_id)
            return
        self._announcer.announce(
            store,
            require_confirmed_vip=True,
            kind="live",
            prefix="Contest started",
            sport_name=sport_name,
            contest_name=name,
            start_date=str(start_date),
            dk_id=dk_id,
            log_label="live",
        )

    def _announce_completed(self, store, dk_id, name, start_date, sport_name) -> None:
        if store.has_notification(dk_id, "completed"):
            logger.info("completed notification already sent for %s dk_id=%s", sport_name, dk_id)
        elif not store.has_notification(dk_id, "live"):
            logger.info(
                "skipping completed notification for %s dk_id=%s; live notification missing",
                sport_name,
                dk_id,
            )
        else:
            self._announcer.announce(
                store,
                require_confirmed_vip=False,
                kind="completed",
                prefix="Contest ended",
                sport_name=sport_name,
                contest_name=name,
                start_date=str(start_date),
                dk_id=dk_id,
                log_label="completed",
            )
