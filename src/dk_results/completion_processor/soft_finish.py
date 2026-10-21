"""Soft-finish: the VIP-cash summary for a live contest that is effectively final.

`SoftFinishAnnouncer.run(store)` checks each sport's primary live contest. When
every leaderboard row shows zero time remaining, it sends one summary (top
score, cash line, cashed VIPs) keyed by a hash of that summary, so a changed
summary is sent again marked "(updated)" and an unchanged one never is.
"""

from __future__ import annotations

import hashlib
import json
import logging
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any

from dk_results.completion_processor.sync import fetch_contest_state
from dk_results.draftkings.leaderboard import leaderboard_cash_cents
from dk_results.notifications.vip_presence import vip_key

if TYPE_CHECKING:
    from dk_results.completion_processor.announcer import MilestoneAnnouncer
    from dk_results.completion_processor.ports import CompletionProcessorConfig
    from dk_results.notifications.vip_presence import ContestResultsPort
    from dk_results.persistence.contestdatabase import ContestDatabase
    from dk_results.persistence.notification_store import NotificationStore

# The package name: log lines keep the `dk_results.completion_processor` logger.
logger = logging.getLogger(__package__)


# ── Pure helpers ─────────────────────────────────────────────────────────────


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


def _resolve_soft_finish_scores(leaderboard_payload: dict[str, Any]) -> tuple[str, str] | None:
    leader = leaderboard_payload.get("leader", {})
    last_winning = leaderboard_payload.get("lastWinningEntry", {})
    top_score = _canonical_score_text(leader.get("fantasyPoints"))
    cashing_score = _canonical_score_text(last_winning.get("fantasyPoints"))
    if top_score is None or cashing_score is None:
        return None
    return top_score, cashing_score


def _row_cashed(row: dict[str, Any]) -> bool:
    return (leaderboard_cash_cents(row) or 0) > 0


def _resolve_cashed_vips(leaderboard_payload: dict[str, Any], vip_keys: set[str]) -> list[str]:
    cashed_lookup: dict[str, str] = {}
    for row in leaderboard_payload.get("leaderBoard", []):
        if not isinstance(row, dict):
            continue
        username_raw = row.get("userName")
        username = str(username_raw).strip() if username_raw is not None else ""
        key = vip_key(username)
        if not key or key not in vip_keys:
            continue
        if not _row_cashed(row):
            continue
        if key not in cashed_lookup:
            cashed_lookup[key] = username
    return _canonical_vips(list(cashed_lookup.values()))


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


class SoftFinishAnnouncer:
    """Announces the soft-finish summary of each sport's primary live contest (needs a sender)."""

    def __init__(
        self,
        *,
        contest_db: ContestDatabase,
        results: ContestResultsPort,
        config: CompletionProcessorConfig,
        announcer: MilestoneAnnouncer,
    ) -> None:
        self._db = contest_db
        self._results = results
        self._config = config
        self._announcer = announcer

    def run(self, store: NotificationStore) -> None:
        for sport_cls in self._config.sport_choices.values():
            live_row = self._db.get_live_contest(
                sport_cls.name,
                sport_cls.sheet_min_entry_fee,
                sport_cls.keyword,
            )
            if not live_row:
                continue
            live_dk_id, live_contest_name, _live_draft_group, _live_positions_paid, live_start_date = live_row
            contest_state = fetch_contest_state(self._results, live_dk_id)
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
                if self._announcer.presence_absent(live_dk_id, str(live_start_date)):
                    logger.info(
                        "skipping soft-finish notification for %s dk_id=%s; vip_presence=absent",
                        sport_cls.name,
                        live_dk_id,
                    )
                    continue
                self._maybe_announce(
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

    def _maybe_announce(
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

        scores = _resolve_soft_finish_scores(leaderboard_payload)
        if scores is None:
            return
        top_score, cashing_score = scores

        vip_keys = {vip_key(name) for name in self._config.vips if vip_key(name)}
        vips_cashed = _resolve_cashed_vips(leaderboard_payload, vip_keys)

        event_key = _soft_finish_event_key(
            sport_name=sport_name,
            dk_id=dk_id,
            top_score=top_score,
            cashing_score=cashing_score,
            vips_cashed=vips_cashed,
        )
        if store.has_notification(dk_id, event_key):
            return

        self._announcer.announce_soft_finish(
            store,
            event_key=event_key,
            sport_name=sport_name,
            contest_name=contest_name,
            start_date=start_date,
            dk_id=dk_id,
            top_score=top_score,
            cashing_score=cashing_score,
            vips_cashed=vips_cashed,
        )
