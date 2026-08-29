"""The contest-completion workflow as one deep module.

`CompletionProcessor` advances each tracked contest and announces its
milestones — starting-soon **warning**, **live**, **completed**, and
**soft-finish** — mirroring the `SportProcessor` pattern. Public entry:
``run(conn)``.

Construction-time dependencies are injected; nothing DraftKings-facing is
constructed inline. The work list (incomplete / live / next-upcoming contests)
is read through `ContestDatabase`; the only external DraftKings edge is
`ContestResultsPort` (per ADR 0001, the completion workflow's own DK slice).

The suppression policy lives here: an ``absent`` presence verdict suppresses an
announcement, ``unknown`` allows it. `VipPresence` stays a pure verdict
provider.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Protocol

from dk_results.domain.sport import Sport
from dk_results.notifications.vip_presence import VIP_ABSENT, ContestResultsPort, vip_key
from dk_results.persistence.contestdatabase import ContestDatabase
from dk_results.persistence.notification_store import NotificationStore
from dk_results.sport_processor import BonusSenderPort

logger = logging.getLogger(__name__)

COMPLETED_STATUSES = ("COMPLETED", "CANCELLED")


# ── Ports ────────────────────────────────────────────────────────────────────


class PresenceOracle(Protocol):
    """The presence-verdict provider the processor consults for suppression."""

    def verdict(self, dk_id: int, start_date: str, vip_names: list[str]) -> str: ...


# ── Config ───────────────────────────────────────────────────────────────────


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
    # Whether milestone announcements may be sent this run. Resolved explicitly
    # at the composition root (from ``DISCORD_NOTIFICATIONS_ENABLED``) and
    # independent of whether a sender is wired: "off" is a deliberate state, so a
    # disabled run still constructs the processor and short-circuits every send.
    notifications_enabled: bool = True


# ── Pure helpers (no config) ─────────────────────────────────────────────────


def _contest_url(dk_id: int) -> str:
    return f"<https://www.draftkings.com/contest/gamecenter/{dk_id}#/>"


def _parse_start_date(start_date: Any) -> datetime.datetime | None:
    if not start_date:
        return None
    if isinstance(start_date, datetime.datetime):
        return start_date
    try:
        return datetime.datetime.fromisoformat(str(start_date))
    except (TypeError, ValueError):
        return None


def _to_decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _is_zero_time_remaining(value: Any) -> bool:
    parsed = _to_decimal(value)
    return parsed is not None and parsed == 0


def _canonical_score_text(value: Any) -> str | None:
    parsed = _to_decimal(value)
    if parsed is None:
        return None
    normalized = parsed.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return f"{normalized:.2f}"


def _leaderboard_cash_value(row: dict[str, Any]) -> Decimal:
    winning_value = _to_decimal(row.get("winningValue"))
    if winning_value is not None:
        return winning_value

    winnings = row.get("winnings")
    if not isinstance(winnings, list):
        return Decimal("0")

    total = Decimal("0")
    for item in winnings:
        if not isinstance(item, dict):
            continue
        description = str(item.get("description", "")).lower()
        if "cash" not in description:
            continue
        cash = _to_decimal(item.get("value"))
        if cash is None:
            continue
        total += cash
    return total


def _soft_finish_eligible(payload: dict[str, Any]) -> bool:
    leader = payload.get("leader")
    last_winning = payload.get("lastWinningEntry")
    leaderboard_rows = payload.get("leaderBoard")
    if not isinstance(leader, dict) or not isinstance(last_winning, dict):
        return False
    if not isinstance(leaderboard_rows, list) or not leaderboard_rows:
        return False
    if not _is_zero_time_remaining(leader.get("timeRemaining")):
        return False
    if not _is_zero_time_remaining(last_winning.get("timeRemaining")):
        return False
    for row in leaderboard_rows:
        if not isinstance(row, dict):
            return False
        if not _is_zero_time_remaining(row.get("timeRemaining")):
            return False
    return True


def _canonical_vips(vips_cashed: list[str]) -> list[str]:
    unique: dict[str, str] = {}
    for name in vips_cashed:
        cleaned = str(name).strip()
        key = vip_key(cleaned)
        if not key or key in unique:
            continue
        unique[key] = cleaned
    return sorted(unique.values(), key=lambda vip: vip.lower())


def _soft_finish_event_key(
    *,
    sport_name: str,
    dk_id: int,
    top_score: Any,
    cashing_score: Any,
    vips_cashed: list[str],
) -> str:
    vip_key_payload = sorted({vip_key(name) for name in vips_cashed if vip_key(name)})
    payload = {
        "sport": sport_name.upper(),
        "dk_id": int(dk_id),
        "top_score": _canonical_score_text(top_score),
        "cashing_score": _canonical_score_text(cashing_score),
        "vips_cashed": vip_key_payload,
    }
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    return f"soft_finish:{digest}"


# ── Module ───────────────────────────────────────────────────────────────────


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

    Suppression policy: a VIP-presence verdict of ``absent`` suppresses an
    announcement; ``unknown`` allows it.
    """

    def __init__(
        self,
        *,
        contest_db: ContestDatabase,
        results: ContestResultsPort,
        presence: PresenceOracle | None,
        bonus_sender: BonusSenderPort | None,
        config: CompletionProcessorConfig,
    ) -> None:
        self._db = contest_db
        self._results = results
        self._presence = presence
        self._sender = bonus_sender
        self._config = config

    def run(self, conn) -> None:
        """Advance and announce every tracked contest's milestones."""
        store = NotificationStore(conn)

        if self._announcing:
            self._run_warnings(store)

        self._sync_and_notify(store)

        if self._announcing:
            self._run_soft_finish(store)

    @property
    def _announcing(self) -> bool:
        """Whether milestone announcements may be sent this run.

        Two independent inputs must both hold: notifications are explicitly
        enabled (``notifications_enabled``) and a sender is wired. Contest-state
        sync runs regardless; only sends are gated.
        """
        return self._config.notifications_enabled and self._sender is not None

    # ── Suppression policy ──────────────────────────────────────────────────

    def _presence_absent(self, dk_id: int, start_date: str) -> bool:
        """Whether presence is ``absent`` (suppress); ``unknown`` allows the send."""
        if self._presence is None:
            return False
        return self._presence.verdict(dk_id, start_date, self._config.vips) == VIP_ABSENT

    def _announce_transition(
        self,
        store: NotificationStore,
        *,
        kind: str,
        prefix: str,
        sport_name: str,
        contest_name: str,
        start_date: str,
        dk_id: int,
        log_label: str,
        log_suffix: str = "",
    ) -> bool:
        """Presence-gated send + record for one announcement.

        Owns the identical ``presence_absent -> send_message -> record_notification``
        dance shared by the warning, live, and completed milestones. The caller keeps
        the ``has_notification`` gate — its wording and elif branches differ per
        milestone. Returns ``True`` when an ``absent`` presence verdict suppressed the
        send, so a caller can short-circuit the rest of its loop iteration.
        """
        assert self._sender is not None
        if self._presence_absent(dk_id, start_date):
            logger.info(
                "skipping %s notification for %s dk_id=%s%s; vip_presence=absent",
                log_label,
                sport_name,
                dk_id,
                log_suffix,
            )
            return True
        message = self._format_contest_announcement(prefix, sport_name, contest_name, start_date, dk_id)
        logger.info("sending %s notification for %s dk_id=%s%s", log_label, sport_name, dk_id, log_suffix)
        self._sender.send_message(message)
        store.record_notification(dk_id, kind)
        logger.info("%s notification stored for %s dk_id=%s%s", log_label, sport_name, dk_id, log_suffix)
        return False

    # ── Warnings ────────────────────────────────────────────────────────────

    def _run_warnings(self, store: NotificationStore) -> None:
        assert self._sender is not None
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
            now = datetime.datetime.now(start_dt.tzinfo)
            # This script runs every 10 minutes via cron, so warnings use windows
            # rather than requiring an exact timestamp match.
            schedule = self._warning_schedule_for(sport_cls.name)
            schedule_key = sport_cls.name.lower()
            if schedule_key not in logged_schedules:
                source = "sport" if schedule_key in self._config.warning_schedules else "default"
                logger.debug(
                    "warning schedule for %s: %s (source=%s)",
                    sport_cls.name,
                    schedule,
                    source,
                )
                logged_schedules.add(schedule_key)
            for warning_minutes in schedule:
                if not (now < start_dt <= now + datetime.timedelta(minutes=warning_minutes)):
                    continue
                warning_key = f"warning:{warning_minutes}"
                if store.has_notification(dk_id, warning_key):
                    logger.debug(
                        "warning already sent for %s dk_id=%s (%sm)",
                        sport_cls.name,
                        dk_id,
                        warning_minutes,
                    )
                    continue
                self._announce_transition(
                    store,
                    kind=warning_key,
                    prefix=f"Contest starting soon ({warning_minutes}m)",
                    sport_name=sport_cls.name,
                    contest_name=name,
                    start_date=str(start_date),
                    dk_id=dk_id,
                    log_label="warning",
                    log_suffix=f" ({warning_minutes}m)",
                )

    def _warning_schedule_for(self, sport_name: str) -> list[int]:
        """Return the warning schedule for a sport, falling back to the default."""
        key = sport_name.lower()
        schedules = self._config.warning_schedules
        return schedules.get(key) or schedules.get("default", self._config.default_warning_schedule)

    # ── State sync + live/completed announcements ───────────────────────────

    def _sync_and_notify(self, store: NotificationStore) -> None:
        incomplete_contests = self._db.get_incomplete_contests()

        if not incomplete_contests:
            return

        logger.debug("found %i incomplete contests", len(incomplete_contests))

        skip_draft_groups: list[int] = []
        sport_choices = self._config.sport_choices

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
            if self._should_skip_contest(dk_id, draft_group, positions_paid, name, skip_draft_groups):
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
                    sport_name,
                    skip_draft_groups,
                )
                if contest_data is not None:
                    self._notify_contest(
                        store,
                        dk_id,
                        name,
                        start_date,
                        sport_name,
                        status,
                        completed,
                        contest_data,
                        sport_choices,
                    )
            except Exception as error:
                logger.error(error)

    @staticmethod
    def _should_skip_contest(
        dk_id: int, draft_group: int, positions_paid: int | None, name: str, skip_draft_groups: list[int]
    ) -> bool:
        if positions_paid is None or draft_group not in skip_draft_groups:
            return False
        logger.debug("dk_id: {} positions_paid: {}".format(dk_id, positions_paid))
        logger.debug(
            "skipping %s because we've already updated %d [skipped draft groups %s]",
            name,
            draft_group,
            " ".join(str(dg) for dg in skip_draft_groups),
        )
        return True

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
        sport_name: str,
        skip_draft_groups: list[int],
    ) -> dict | None:
        logger.debug(
            "getting contest data for %s [id: %i start: %s dg: %d]",
            name,
            dk_id,
            start_date,
            draft_group,
        )
        contest_data = self._get_contest_data(dk_id)
        if contest_data is None:
            return None
        logger.debug(
            "existing: status: %s entries: %s positions_paid: %s",
            status,
            entries,
            positions_paid,
        )
        logger.debug(contest_data)
        new_status = contest_data["status"]
        new_completed = contest_data["completed"]
        if positions_paid != contest_data["positions_paid"] or status != new_status or completed != new_completed:
            self._db.update_contest(
                dk_id,
                positions_paid=contest_data["positions_paid"],
                status=new_status,
                completed=new_completed,
            )
        else:
            skip_draft_groups.append(draft_group)
            logger.debug("contest data is the same, not updating")
        return contest_data

    def _notify_contest(
        self,
        store: NotificationStore,
        dk_id: int,
        name: str,
        start_date: object,
        sport_name: str,
        status: str,
        completed: int,
        contest_data: dict[str, Any],
        sport_choices: Mapping[str, type[Sport]],
    ) -> None:
        if not self._announcing or sport_name not in sport_choices:
            return
        assert self._sender is not None
        new_status = contest_data["status"]
        new_completed = contest_data["completed"]
        sport_cls = sport_choices[sport_name]
        live_row = self._db.get_live_contest(sport_cls.name, sport_cls.sheet_min_entry_fee, sport_cls.keyword)
        is_primary_live = bool(live_row and live_row[0] == dk_id)
        if status != "LIVE" and new_status == "LIVE" and is_primary_live:
            self._announce_live(store, dk_id, name, start_date, sport_name)
        is_new_completed = (status not in COMPLETED_STATUSES and new_status in COMPLETED_STATUSES) or (
            completed == 0 and new_completed == 1
        )
        if is_new_completed:
            self._announce_completed(store, dk_id, name, start_date, sport_name)

    def _announce_live(self, store, dk_id, name, start_date, sport_name) -> None:
        logger.info("live transition detected for %s dk_id=%s", sport_name, dk_id)
        if store.has_notification(dk_id, "live"):
            logger.info("live notification already sent for %s dk_id=%s", sport_name, dk_id)
            return
        self._announce_transition(
            store,
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
            self._announce_transition(
                store,
                kind="completed",
                prefix="Contest ended",
                sport_name=sport_name,
                contest_name=name,
                start_date=str(start_date),
                dk_id=dk_id,
                log_label="completed",
            )

    def _get_contest_data(self, dk_id) -> dict | None:
        try:
            response_json = self._results.get_contest_detail(dk_id)
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
            logger.error(f"JSON decoding error: {val_err}")
        except KeyError as key_err:
            logger.error(f"Key error: {key_err}")
        except Exception as req_ex:
            logger.error(f"Request error: {req_ex}")

        return None

    # ── Soft-finish ─────────────────────────────────────────────────────────

    def _run_soft_finish(self, store: NotificationStore) -> None:
        for sport_cls in self._config.sport_choices.values():
            live_row = self._db.get_live_contest(
                sport_cls.name,
                sport_cls.sheet_min_entry_fee,
                sport_cls.keyword,
            )
            if not live_row:
                continue
            live_dk_id, live_contest_name, _live_draft_group, _live_positions_paid, live_start_date = live_row
            contest_state = self._get_contest_data(live_dk_id)
            if not isinstance(contest_state, dict):
                continue

            state_status = contest_state.get("status")
            state_completed = contest_state.get("completed")
            if not isinstance(state_status, str):
                continue
            if type(state_completed) is not int:
                continue
            if state_status != "LIVE" or state_completed != 0:
                continue

            try:
                if self._presence_absent(live_dk_id, str(live_start_date)):
                    logger.info(
                        "skipping soft-finish notification for %s dk_id=%s; vip_presence=absent",
                        sport_cls.name,
                        live_dk_id,
                    )
                    continue
                self._maybe_send_soft_finish_announcement(
                    store,
                    sport_name=sport_cls.name,
                    contest_name=str(live_contest_name),
                    start_date=str(live_start_date),
                    dk_id=int(live_dk_id),
                )
            except Exception:
                logger.warning(
                    "soft-finish evaluation failed for %s dk_id=%s",
                    sport_cls.name,
                    live_dk_id,
                    exc_info=True,
                )

    def _maybe_send_soft_finish_announcement(
        self,
        store: NotificationStore,
        *,
        sport_name: str,
        contest_name: str,
        start_date: str,
        dk_id: int,
    ) -> None:
        leaderboard_payload = self._results.get_leaderboard(dk_id)
        if not _soft_finish_eligible(leaderboard_payload):
            return

        leader = leaderboard_payload.get("leader", {})
        last_winning = leaderboard_payload.get("lastWinningEntry", {})
        top_score_raw = leader.get("fantasyPoints")
        cashing_score_raw = last_winning.get("fantasyPoints")
        top_score = _canonical_score_text(top_score_raw)
        cashing_score = _canonical_score_text(cashing_score_raw)
        if top_score is None or cashing_score is None:
            return

        vip_keys = {vip_key(name) for name in self._config.vips if vip_key(name)}
        cashed_lookup: dict[str, str] = {}
        for row in leaderboard_payload.get("leaderBoard", []):
            if not isinstance(row, dict):
                continue
            username_raw = row.get("userName")
            username = str(username_raw).strip() if username_raw is not None else ""
            key = vip_key(username)
            if not key or key not in vip_keys:
                continue
            if _leaderboard_cash_value(row) <= 0:
                continue
            if key not in cashed_lookup:
                cashed_lookup[key] = username
        vips_cashed = _canonical_vips(list(cashed_lookup.values()))

        event_key = _soft_finish_event_key(
            sport_name=sport_name,
            dk_id=dk_id,
            top_score=top_score,
            cashing_score=cashing_score,
            vips_cashed=vips_cashed,
        )
        if store.has_notification(dk_id, event_key):
            return

        assert self._sender is not None
        is_update = store.has_any_soft_finish_notification(dk_id)
        message = self._format_soft_finish_announcement(
            sport_name=sport_name,
            contest_name=contest_name,
            start_date=start_date,
            dk_id=dk_id,
            top_score=top_score,
            cashing_score=cashing_score,
            vips_cashed=vips_cashed,
            is_update=is_update,
        )
        self._sender.send_message(message)
        store.record_notification(dk_id, event_key)

    # ── Presentation ────────────────────────────────────────────────────────

    def _sport_emoji(self, sport_name: str) -> str:
        return self._config.sport_emoji.get(sport_name, "🏟️")

    def _sheet_link(self, sheet_title: str) -> str | None:
        if not self._config.spreadsheet_id:
            return None
        gid = self._config.sheet_gid_map.get(sheet_title)
        if gid is None:
            return None
        return f"<https://docs.google.com/spreadsheets/d/{self._config.spreadsheet_id}/edit#gid={gid}>"

    def _format_contest_announcement(
        self,
        prefix: str,
        sport_name: str,
        contest_name: str,
        start_date: str,
        dk_id: int,
    ) -> str:
        url = _contest_url(dk_id)
        sheet_link = self._sheet_link(sport_name)
        sheet_part = f"📊 Sheet: [{sport_name}]({sheet_link})" if sheet_link else "📊 Sheet: n/a"
        relative = None
        start_dt = _parse_start_date(start_date)
        if start_dt:
            delta = start_dt - datetime.datetime.now(start_dt.tzinfo)
            if delta.total_seconds() > 0:
                seconds = int(delta.total_seconds())
                minutes, sec = divmod(seconds, 60)
                hours, minutes = divmod(minutes, 60)
                days, hours = divmod(hours, 24)
                parts = []
                if days:
                    parts.append(f"{days}d")
                if hours:
                    parts.append(f"{hours}h")
                if minutes:
                    parts.append(f"{minutes}m")
                if not parts:
                    parts.append(f"{sec}s")
                relative = "".join(parts)
        relative_part = f" (⏳ {relative})" if relative else ""
        return "\n".join(
            [
                f"{prefix}: {self._sport_emoji(sport_name)} {sport_name} — {contest_name}",
                f"• 🕒 {start_date}{relative_part}",
                f"• 🔗 DK: [{dk_id}]({url})",
                f"• {sheet_part}",
            ]
        )

    def _format_soft_finish_announcement(
        self,
        *,
        sport_name: str,
        contest_name: str,
        start_date: str,
        dk_id: int,
        top_score: str,
        cashing_score: str,
        vips_cashed: list[str],
        is_update: bool = False,
    ) -> str:
        vip_text = ", ".join(vips_cashed) if vips_cashed else "none"
        prefix = "Contest soft-finished (updated)" if is_update else "Contest soft-finished"
        base = self._format_contest_announcement(
            prefix,
            sport_name,
            contest_name,
            start_date,
            dk_id,
        )
        return "\n".join(
            [
                base,
                f"• 🏆 Top score: {top_score}",
                f"• 💵 Cashing score: {cashing_score}",
                f"• ⭐ VIPs cashed (visible rows): {vip_text}",
            ]
        )
