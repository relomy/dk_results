"""Bonus announcement aggregation, dedupe, and webhook delivery."""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from typing import Any

from classes.bonus_rules import parse_bonus_counts
from classes.lineup import normalize_name


@dataclass
class BonusCandidate:
    display_name: str
    normalized_player_name: str
    bonus_code: str
    new_count: int
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
    conn.commit()


def _format_vip_users(vip_users: list[str], limit: int = 5) -> str:
    sorted_users = sorted(vip_users, key=str.lower)
    shown = sorted_users[:limit]
    remaining = len(sorted_users) - len(shown)
    user_list = ", ".join(shown)
    if remaining > 0:
        return f"{user_list} +{remaining} more"
    return user_list


def _format_message(sport: str, candidate: BonusCandidate, announced_count: int) -> str:
    vip_part = _format_vip_users(candidate.vip_users)
    if sport == "NBA":
        if candidate.bonus_code == "TDbl":
            action = "achieved a triple-double"
        else:
            action = "achieved a double-double"
        return (
            f"{sport}: {candidate.display_name} {action} "
            f"(VIPs: {vip_part})"
        )
    return (
        f"{sport}: {candidate.display_name} has {announced_count} "
        f"{candidate.bonus_code} (VIPs: {vip_part})"
    )


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


def _collect_candidates(
    sport: str, vip_lineups: list[dict[str, Any]]
) -> list[BonusCandidate]:
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for vip_lineup in vip_lineups:
        vip_name = str(vip_lineup.get("user", "")).strip()
        players = vip_lineup.get("players", [])
        for player in players:
            display_name = str(player.get("name", "")).strip()
            normalized_name = normalize_name(display_name)
            if not normalized_name:
                continue
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
                        "vips": set(),
                    }
                grouped[key]["display_names"].add(display_name or normalized_name)
                grouped[key]["count"] = max(grouped[key]["count"], count)
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

    create_bonus_announcements_table(conn)
    candidates = _collect_candidates(sport, vip_lineups)
    if not candidates:
        return 0

    sent_messages = 0
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

        if sport == "NBA":
            counts_to_announce = [1]
        else:
            counts_to_announce = list(range(old_count + 1, new_count + 1))

        try:
            for count_value in counts_to_announce:
                sender.send_message(_format_message(sport, candidate, count_value))
                sent_messages += 1
        except Exception as err:
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
                log.info(
                    "Skipping DB advance for %s %s in contest %s; count changed in another run.",
                    candidate.normalized_player_name,
                    candidate.bonus_code,
                    contest_id,
                )
        except sqlite3.Error as err:
            log.error(
                "Failed to persist bonus announcement for %s %s in contest %s: %s",
                candidate.normalized_player_name,
                candidate.bonus_code,
                contest_id,
                err,
            )

    return sent_messages
