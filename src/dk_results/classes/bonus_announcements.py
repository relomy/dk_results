"""Bonus announcement aggregation, dedupe, and webhook delivery."""

from __future__ import annotations

import logging
import sqlite3
import time
from dataclasses import dataclass
from typing import Any

from dk_results.classes.bonus_rules import parse_bonus_counts
from dk_results.classes.lineup import normalize_name

BONUS_META: dict[str, dict[str, dict[str, Any]]] = {
    "GOLF": {
        "EAG": {
            "label": "eagle",
            "action": "recorded an eagle",
            "points": 8,
            "count_mode": "incremental",
        },
        "BOFR": {
            "label": "bogey-free round",
            "action": "recorded a bogey-free round",
            "points": 3,
            "count_mode": "incremental",
        },
        "BIR3+": {
            "label": "birdie streak",
            "action": "recorded a birdie streak",
            "points": 3,
            "count_mode": "incremental",
        },
    },
    "NBA": {
        "DDbl": {
            "label": "double-double",
            "action": "achieved a double-double",
            "points": 1.5,
            "count_mode": "binary",
        },
        "TDbl": {
            "label": "triple-double",
            "action": "achieved a triple-double",
            "points": 3,
            "count_mode": "binary",
        },
    },
}


@dataclass
class BonusCandidate:
    display_name: str
    normalized_player_name: str
    bonus_code: str
    new_count: int
    max_ownership: float
    vip_users: list[str]


def create_bonus_announcements_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS bonus_announcements (
            contest_id INTEGER NOT NULL,
            sport TEXT NOT NULL,
            normalized_player_name TEXT NOT NULL,
            bonus_code TEXT NOT NULL,
            last_announced_count INTEGER NOT NULL DEFAULT 0,
            updated_at datetime NOT NULL DEFAULT (datetime('now', 'localtime'))
        );
        """
    )
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS bonus_announcements_unique_key
        ON bonus_announcements (contest_id, sport, normalized_player_name, bonus_code);
        """
    )


def _format_vip_users(vip_users: list[str], limit: int = 5) -> str:
    sorted_users = sorted(vip_users, key=str.lower)
    shown = sorted_users[:limit]
    remaining = len(sorted_users) - len(shown)
    user_list = ", ".join(shown)
    if remaining > 0:
        return f"{user_list} +{remaining} more"
    return user_list


def _format_points(points: float) -> str:
    if int(points) == points:
        return str(int(points))
    return f"{points:.1f}".rstrip("0").rstrip(".")


def _format_ownership(ownership: float) -> str:
    return f"{ownership * 100:.1f}%"


def _get_bonus_meta(sport: str, bonus_code: str) -> dict[str, Any]:
    return BONUS_META.get(sport, {}).get(
        bonus_code,
        {
            "label": bonus_code,
            "action": f"recorded a {bonus_code}",
            "points": 0,
            "count_mode": "incremental",
        },
    )


def _format_message(sport: str, candidate: BonusCandidate, announced_count: int) -> str:
    meta = _get_bonus_meta(sport, candidate.bonus_code)
    vip_part = _format_vip_users(candidate.vip_users)
    ownership = _format_ownership(candidate.max_ownership)
    points = float(meta["points"])
    points_text = f"+{_format_points(points)} pts"
    if meta["count_mode"] == "incremental" and announced_count > 1:
        total_points = points * announced_count
        points_text = f"{points_text}, {_format_points(total_points)} total bonus pts"
    action = meta["action"]
    return f"{sport}: {candidate.display_name} ({ownership}) {action} ({points_text}) (VIPs: {vip_part})"


def _load_old_count(
    conn: sqlite3.Connection,
    contest_id: int,
    sport: str,
    normalized_player_name: str,
    bonus_code: str,
) -> int:
    row = conn.execute(
        """
        SELECT last_announced_count
        FROM bonus_announcements
        WHERE contest_id=? AND sport=? AND normalized_player_name=? AND bonus_code=?
        """,
        (contest_id, sport, normalized_player_name, bonus_code),
    ).fetchone()
    return int(row[0]) if row else 0


def _ensure_row_exists(
    conn: sqlite3.Connection,
    contest_id: int,
    sport: str,
    normalized_player_name: str,
    bonus_code: str,
) -> None:
    conn.execute(
        """
        INSERT INTO bonus_announcements (
            contest_id, sport, normalized_player_name, bonus_code, last_announced_count
        )
        VALUES (?, ?, ?, ?, 0)
        ON CONFLICT (contest_id, sport, normalized_player_name, bonus_code) DO NOTHING
        """,
        (contest_id, sport, normalized_player_name, bonus_code),
    )


def _cas_update_count(
    conn: sqlite3.Connection,
    contest_id: int,
    sport: str,
    normalized_player_name: str,
    bonus_code: str,
    old_count: int,
    new_count: int,
) -> bool:
    cur = conn.execute(
        """
        UPDATE bonus_announcements
        SET last_announced_count=?, updated_at=datetime('now', 'localtime')
        WHERE contest_id=? AND sport=? AND normalized_player_name=? AND bonus_code=?
          AND last_announced_count=?
        """,
        (
            new_count,
            contest_id,
            sport,
            normalized_player_name,
            bonus_code,
            old_count,
        ),
    )
    return cur.rowcount > 0


def _collect_candidates(sport: str, vip_lineups: list[dict[str, Any]]) -> list[BonusCandidate]:
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for vip_lineup in vip_lineups:
        vip_name = str(vip_lineup.get("user", "")).strip()
        players = vip_lineup.get("players", [])
        for player in players:
            display_name = str(player.get("name", "")).strip()
            normalized_name = normalize_name(display_name)
            if not normalized_name:
                continue
            raw_ownership = player.get("ownership", 0)
            try:
                ownership = float(raw_ownership)
            except (TypeError, ValueError):
                ownership = 0.0
            ownership = max(0.0, min(1.0, ownership))
            bonus_counts = parse_bonus_counts(sport, str(player.get("stats", "")))
            if not bonus_counts:
                continue
            for bonus_code, count in bonus_counts.items():
                if count <= 0:
                    continue
                key = (normalized_name, bonus_code)
                if key not in grouped:
                    grouped[key] = {
                        "display_names": set(),
                        "count": count,
                        "max_ownership": ownership,
                        "vips": set(),
                    }
                grouped[key]["display_names"].add(display_name or normalized_name)
                grouped[key]["count"] = max(grouped[key]["count"], count)
                grouped[key]["max_ownership"] = max(grouped[key]["max_ownership"], ownership)
                if vip_name:
                    grouped[key]["vips"].add(vip_name)
    candidates: list[BonusCandidate] = []
    for (normalized_name, bonus_code), data in sorted(grouped.items()):
        canonical_display_name = sorted(data["display_names"], key=str.lower)[0]
        candidates.append(
            BonusCandidate(
                display_name=canonical_display_name,
                normalized_player_name=normalized_name,
                bonus_code=bonus_code,
                new_count=int(data["count"]),
                max_ownership=float(data["max_ownership"]),
                vip_users=sorted(list(data["vips"]), key=str.lower),
            )
        )
    return candidates


def announce_vip_bonuses(
    *,
    conn: sqlite3.Connection,
    sport: str,
    contest_id: int,
    vip_lineups: list[dict[str, Any]],
    sender: Any | None,
    logger: logging.Logger | None = None,
) -> int:
    """Announce newly observed bonus opportunities for VIP lineups."""
    log = logger or logging.getLogger(__name__)
    if not sender or not vip_lineups:
        return 0

    started_at = time.monotonic()
    log.info(
        "Starting VIP bonus announcements: sport=%s contest_id=%s vip_lineups=%d",
        sport,
        contest_id,
        len(vip_lineups),
    )

    create_bonus_announcements_table(conn)
    candidates = _collect_candidates(sport, vip_lineups)
    if not candidates:
        elapsed_ms = int((time.monotonic() - started_at) * 1000)
        log.info(
            "Completed VIP bonus announcements: sport=%s contest_id=%s "
            "candidates=0 persisted=0 webhook_messages=0 send_failures=0 "
            "db_failures=0 cas_skips=0 elapsed_ms=%d",
            sport,
            contest_id,
            elapsed_ms,
        )
        return 0

    by_bonus: dict[str, int] = {}
    for candidate in candidates:
        by_bonus[candidate.bonus_code] = by_bonus.get(candidate.bonus_code, 0) + 1
    log.debug(
        "VIP bonus candidate aggregate: sport=%s contest_id=%s candidates=%d by_bonus=%s",
        sport,
        contest_id,
        len(candidates),
        dict(sorted(by_bonus.items())),
    )

    persisted_announcements = 0
    webhook_messages = 0
    send_failures = 0
    db_failures = 0
    cas_skips = 0
    for candidate in candidates:
        old_count = _load_old_count(
            conn,
            contest_id,
            sport,
            candidate.normalized_player_name,
            candidate.bonus_code,
        )
        new_count = candidate.new_count
        if new_count <= old_count:
            continue

        meta = _get_bonus_meta(sport, candidate.bonus_code)
        if meta["count_mode"] == "binary":
            counts_to_announce = [1]
        else:
            counts_to_announce = list(range(old_count + 1, new_count + 1))
        log.debug(
            "VIP bonus transition: sport=%s contest_id=%s player=%s bonus=%s "
            "old_count=%d new_count=%d messages_to_send=%d",
            sport,
            contest_id,
            candidate.normalized_player_name,
            candidate.bonus_code,
            old_count,
            new_count,
            len(counts_to_announce),
        )

        try:
            for count_value in counts_to_announce:
                sender.send_message(_format_message(sport, candidate, count_value))
            webhook_messages += len(counts_to_announce)
        except Exception as err:
            send_failures += 1
            log.error(
                "Failed to send bonus announcement for %s %s in contest %s: %s",
                candidate.normalized_player_name,
                candidate.bonus_code,
                contest_id,
                err,
            )
            continue

        try:
            _ensure_row_exists(
                conn,
                contest_id,
                sport,
                candidate.normalized_player_name,
                candidate.bonus_code,
            )
            updated = _cas_update_count(
                conn,
                contest_id,
                sport,
                candidate.normalized_player_name,
                candidate.bonus_code,
                old_count,
                new_count,
            )
            conn.commit()
            if not updated:
                cas_skips += 1
                log.debug(
                    "Skipping DB advance for %s %s in contest %s; count changed in another run.",
                    candidate.normalized_player_name,
                    candidate.bonus_code,
                    contest_id,
                )
                continue
            persisted_announcements += len(counts_to_announce)
        except sqlite3.Error as err:
            db_failures += 1
            log.error(
                "Failed to persist bonus announcement for %s %s in contest %s: %s",
                candidate.normalized_player_name,
                candidate.bonus_code,
                contest_id,
                err,
            )

    elapsed_ms = int((time.monotonic() - started_at) * 1000)
    log.info(
        "Completed VIP bonus announcements: sport=%s contest_id=%s candidates=%d "
        "persisted=%d webhook_messages=%d send_failures=%d db_failures=%d "
        "cas_skips=%d elapsed_ms=%d",
        sport,
        contest_id,
        len(candidates),
        persisted_announcements,
        webhook_messages,
        send_failures,
        db_failures,
        cas_skips,
        elapsed_ms,
    )

    return persisted_announcements
