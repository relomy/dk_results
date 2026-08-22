"""Persistence for contest-notification idempotency and VIP-presence caching.

`NotificationStore` is the single writer of the ``contest_notifications`` and
``contest_vip_presence`` tables. It keeps a milestone from being announced twice
and caches VIP-presence verdicts. It shares one sqlite file with
``ContestDatabase`` but owns a disjoint set of tables (see ADR 0002).
"""

from __future__ import annotations

import logging
import sqlite3

logger = logging.getLogger(__name__)


class NotificationStore:
    """Announcement bookkeeping and VIP-presence cache over a sqlite connection."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._create_tables()

    def _create_tables(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS contest_notifications (
                dk_id INTEGER NOT NULL,
                event TEXT NOT NULL,
                announced_at datetime NOT NULL DEFAULT (datetime('now', 'localtime')),
                PRIMARY KEY (dk_id, event)
            );
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS contest_vip_presence (
                dk_id INTEGER PRIMARY KEY,
                status TEXT NOT NULL,
                checked_at datetime NOT NULL DEFAULT (datetime('now', 'localtime'))
            );
            """
        )
        self._conn.commit()

    # ── Notification bookkeeping ───────────────────────────────────────────────

    def has_notification(self, dk_id: int, event: str) -> bool:
        """Whether ``event`` has already been announced for ``dk_id``."""
        cur = self._conn.execute(
            "SELECT 1 FROM contest_notifications WHERE dk_id=? AND event=? LIMIT 1",
            (dk_id, event),
        )
        return cur.fetchone() is not None

    def has_any_soft_finish_notification(self, dk_id: int) -> bool:
        """Whether any soft-finish event has been announced for ``dk_id``."""
        cur = self._conn.execute(
            "SELECT 1 FROM contest_notifications WHERE dk_id=? AND event LIKE 'soft_finish:%' LIMIT 1",
            (dk_id,),
        )
        return cur.fetchone() is not None

    def record_notification(self, dk_id: int, event: str) -> None:
        """Record that ``event`` was announced for ``dk_id`` (idempotent)."""
        try:
            self._conn.execute(
                "INSERT OR IGNORE INTO contest_notifications (dk_id, event) VALUES (?, ?)",
                (dk_id, event),
            )
            self._conn.commit()
        except (sqlite3.Error, AttributeError) as err:
            logger.error("sqlite error inserting notification: %s", err)

    # ── VIP-presence cache ─────────────────────────────────────────────────────

    def get_presence(self, dk_id: int) -> tuple[str, str] | None:
        """Return the cached ``(status, checked_at)`` for ``dk_id``, or ``None``."""
        cur = self._conn.execute(
            "SELECT status, checked_at FROM contest_vip_presence WHERE dk_id=? LIMIT 1",
            (dk_id,),
        )
        return cur.fetchone()

    def upsert_presence(self, dk_id: int, status: str) -> None:
        """Insert or replace the cached presence ``status`` for ``dk_id``."""
        self._conn.execute(
            """
            INSERT INTO contest_vip_presence (dk_id, status)
            VALUES (?, ?)
            ON CONFLICT(dk_id) DO UPDATE SET
                status=excluded.status,
                checked_at=datetime('now', 'localtime')
            """,
            (dk_id, status),
        )
        self._conn.commit()
