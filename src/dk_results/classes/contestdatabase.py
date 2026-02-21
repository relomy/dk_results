import datetime
import logging
import sqlite3

from dk_results.classes.contest import Contest
from dk_results.logging import configure_logging

configure_logging()


class ContestDatabase:
    def __init__(self, sqlite3_database: str, logger: logging.Logger | None = None) -> None:
        """
        Initialize ContestDatabase with SQLite database file.

        Args:
            sqlite3_database (str): Path to SQLite database file.
            logger (logging.Logger, optional): Logger instance.
        """
        self.logger = logger or logging.getLogger(__name__)
        self.sqlite_path = sqlite3_database
        self.logger.info("Connecting to contests DB %s", self.sqlite_path)
        self.conn: sqlite3.Connection = sqlite3.connect(sqlite3_database)

    def create_table(self) -> None:
        """
        Create the contests table if it does not exist.
        """
        sql = """
        CREATE TABLE IF NOT EXISTS "contests" (
            "dk_id" INTEGER PRIMARY KEY,
            "sport" varchar(10) NOT NULL,
            "name"  varchar(50) NOT NULL,
            "start_date"    datetime NOT NULL,
            "draft_group"   INTEGER NOT NULL,
            "total_prizes"  INTEGER NOT NULL,
            "entries"       INTEGER NOT NULL,
            "positions_paid"        INTEGER,
            "entry_fee"     INTEGER NOT NULL,
            "entry_count"   INTEGER NOT NULL,
            "max_entry_count"       INTEGER NOT NULL,
            "completed"     INTEGER NOT NULL DEFAULT 0,
            "status"        TEXT
        );
        """
        self.conn.execute(sql)
        self.conn.commit()

    def compare_contests(self, contests: list[Contest]) -> list[int]:
        """
        Compare given contests with those in the database and return new contest IDs.

        Args:
            contests (list[Contest]): List of Contest objects.

        Returns:
            list[int]: List of new contest IDs not found in the database.
        """
        dk_ids = [c.id for c in contests]
        if not dk_ids:
            return []
        sql = "SELECT dk_id FROM contests WHERE dk_id IN ({})".format(", ".join("?" for _ in dk_ids))
        cur = self.conn.cursor()
        cur.execute(sql, dk_ids)
        rows = cur.fetchall()
        found_ids = {row[0] for row in rows}
        return [dk_id for dk_id in dk_ids if dk_id not in found_ids]

    def insert_contests(self, contests: list[Contest]) -> None:
        """
        Insert contests into the database, ignoring duplicates.

        Args:
            contests (list[Contest]): List of Contest objects.
        """
        columns = [
            "sport",
            "dk_id",
            "name",
            "start_date",
            "draft_group",
            "total_prizes",
            "entries",
            "entry_fee",
            "entry_count",
            "max_entry_count",
        ]
        sql = "INSERT OR IGNORE INTO contests ({}) VALUES ({});".format(
            ", ".join(columns), ", ".join("?" for _ in columns)
        )
        cur = self.conn.cursor()
        for contest in contests:
            tpl_contest = (
                contest.sport,
                contest.id,
                contest.name,
                contest.start_dt,
                contest.draft_group,
                contest.total_prizes,
                contest.entries,
                contest.entry_fee,
                contest.entry_count,
                contest.max_entry_count,
            )
            cur.execute(sql, tpl_contest)
        self.conn.commit()

    def close(self) -> None:
        """
        Close the database connection.
        """
        self.conn.close()

    def sync_draft_group_start_dates(self, draft_group_start_dates: dict[int, datetime.datetime]) -> int:
        """
        Update start_date for contests in draft groups when the start time changes.

        Args:
            draft_group_start_dates (dict[int, datetime.datetime]): Draft group IDs
                mapped to their latest start datetime (naive, seconds precision).

        Returns:
            int: Number of draft groups updated (not rows updated).
        """
        if not draft_group_start_dates:
            return 0

        draft_group_ids = sorted(draft_group_start_dates.keys())
        cur = self.conn.cursor()
        sql = "SELECT draft_group, start_date FROM contests WHERE draft_group IN ({})".format(
            ", ".join("?" for _ in draft_group_ids)
        )
        cur.execute(sql, draft_group_ids)
        rows = cur.fetchall()
        if not rows:
            return 0

        groups_to_update: dict[int, str] = {}
        for draft_group, start_date in rows:
            new_dt = draft_group_start_dates.get(draft_group)
            if new_dt is None:
                continue
            new_dt = new_dt.replace(microsecond=0)
            try:
                existing_dt = datetime.datetime.fromisoformat(str(start_date)).replace(microsecond=0)
            except (TypeError, ValueError):
                existing_dt = None
            if existing_dt != new_dt:
                groups_to_update[draft_group] = new_dt.isoformat(sep=" ")

        updates = 0
        for draft_group, new_dt_str in groups_to_update.items():
            cur.execute(
                "UPDATE contests SET start_date=? WHERE draft_group=? AND start_date!=?",
                (new_dt_str, draft_group, new_dt_str),
            )
            if cur.rowcount:
                updates += 1
        self.conn.commit()
        return updates

    def get_live_contest(self, sport: str, entry_fee: int = 25, keyword: str = "%") -> tuple | None:
        """
        Get a live contest matching the criteria. Prefer contests at or above the
        minimum entry fee; if none exist, fall back to the highest entry fee
        below the minimum.

        Args:
            sport (str): Sport name.
            entry_fee (int, optional): Minimum entry fee. Defaults to 25.
            keyword (str, optional): Name keyword pattern. Defaults to "%".

        Returns:
            tuple | None: (dk_id, name, draft_group, positions_paid, start_date) if found, else None.
        """
        cur = self.conn.cursor()
        try:
            base_sql = (
                "SELECT dk_id, name, draft_group, positions_paid, start_date "
                "FROM contests "
                "WHERE sport=? "
                "  AND name LIKE ? "
                "  AND start_date <= datetime('now', 'localtime') "
                "  AND completed=0 "
            )

            ordering = " ORDER BY entry_fee DESC, entries DESC, start_date DESC, dk_id DESC LIMIT 1"

            cur.execute(base_sql + "  AND entry_fee >= ?" + ordering, (sport, keyword, entry_fee))
            row = cur.fetchone()
            if row:
                self.logger.debug("returning %s", row)
                return row

            cur.execute(base_sql + "  AND entry_fee < ?" + ordering, (sport, keyword, entry_fee))
            row = cur.fetchone()
            self.logger.debug("returning %s", row)
            return row
        except sqlite3.Error as err:
            self.logger.error(
                "sqlite error in get_live_contest() (%s): %s",
                self.sqlite_path,
                err.args[0],
            )

    def get_live_contests(
        self, sports: list[str] | None = None, entry_fee: int = 25, keyword: str = "%"
    ) -> list[tuple]:
        """
        Get one live contest per sport, using the same fallback as get_live_contest:
        prefer contests at or above the minimum entry fee; if none exist for a sport,
        fall back to the highest entry fee below the minimum.

        Args:
            sports (list[str] | None): Sport names to include; if None, include all.
            entry_fee (int, optional): Minimum entry fee. Defaults to 25.
            keyword (str, optional): Name keyword pattern. Defaults to "%".

        Returns:
            list[tuple]: Each tuple is (dk_id, name, draft_group, positions_paid, start_date, sport).
        """
        cur = self.conn.cursor()
        try:
            sport_list = list(sports) if sports else []

            if not sport_list:
                cur.execute(
                    """
                    SELECT DISTINCT sport
                    FROM contests
                    WHERE name LIKE ?
                      AND start_date <= datetime('now', 'localtime')
                      AND completed=0
                    """,
                    (keyword,),
                )
                sport_list = [row[0] for row in cur.fetchall()]

            rows: list[tuple] = []
            for sport_name in sorted(sport_list):
                live = self.get_live_contest(sport_name, entry_fee, keyword)
                if live:
                    dk_id, name, draft_group, positions_paid, start_date = live
                    rows.append((dk_id, name, draft_group, positions_paid, start_date, sport_name))

            self.logger.debug("returning %d live contests", len(rows))
            return rows
        except sqlite3.Error as err:
            self.logger.error("sqlite error in get_live_contests(): %s", err.args[0])
            return []

    def get_next_upcoming_contest(self, sport: str, entry_fee: int = 25, keyword: str = "%") -> tuple | None:
        """
        Get the next upcoming contest matching the criteria.

        Args:
            sport (str): Sport name.
            entry_fee (int, optional): Minimum entry fee. Defaults to 25.
            keyword (str, optional): Name keyword pattern. Defaults to "%".

        Returns:
            tuple | None: (dk_id, name, draft_group, positions_paid, start_date) if found, else None.
        """
        cur = self.conn.cursor()
        try:
            sql = (
                "SELECT dk_id, name, draft_group, positions_paid, start_date "
                "FROM contests "
                "WHERE sport=? "
                "  AND name LIKE ? "
                "  AND entry_fee >= ? "
                "  AND start_date > datetime('now', 'localtime') "
                "  AND completed=0 "
                "ORDER BY start_date ASC, entry_fee DESC, entries DESC "
                "LIMIT 1"
            )
            cur.execute(sql, (sport, keyword, entry_fee))
            row = cur.fetchone()
            self.logger.debug("returning %s", row)
            return row if row else None
        except sqlite3.Error as err:
            self.logger.error("sqlite error in get_next_upcoming_contest(): %s", err.args[0])
            return None

    def get_next_upcoming_contest_any(self, sport: str) -> tuple | None:
        """
        Get the next upcoming contest for a sport, regardless of criteria.

        Args:
            sport (str): Sport name.

        Returns:
            tuple | None: (dk_id, name, draft_group, positions_paid, start_date) if found, else None.
        """
        cur = self.conn.cursor()
        try:
            sql = (
                "SELECT dk_id, name, draft_group, positions_paid, start_date "
                "FROM contests "
                "WHERE sport=? "
                "  AND start_date > datetime('now', 'localtime') "
                "  AND completed=0 "
                "ORDER BY start_date ASC, entry_fee DESC, entries DESC "
                "LIMIT 1"
            )
            cur.execute(sql, (sport,))
            row = cur.fetchone()
            self.logger.debug("returning %s", row)
            return row if row else None
        except sqlite3.Error as err:
            self.logger.error("sqlite error in get_next_upcoming_contest_any(): %s", err.args[0])
            return None

    def get_contest_by_id(self, dk_id: int) -> tuple | None:
        """
        Get one contest by dk_id.

        Returns:
            tuple | None: (dk_id, name, draft_group, positions_paid, start_date, entry_fee, entries)
        """
        cur = self.conn.cursor()
        try:
            sql = (
                "SELECT dk_id, name, draft_group, positions_paid, start_date, entry_fee, entries "
                "FROM contests "
                "WHERE dk_id=? "
                "LIMIT 1"
            )
            cur.execute(sql, (dk_id,))
            return cur.fetchone()
        except sqlite3.Error as err:
            self.logger.error("sqlite error in get_contest_by_id(): %s", err.args[0])
            return None

    def get_contest_state(self, dk_id: int) -> tuple[str | None, int | None] | None:
        """Fetch state and completion flags for one contest."""
        cur = self.conn.cursor()
        try:
            sql = "SELECT status, completed FROM contests WHERE dk_id=? LIMIT 1"
            cur.execute(sql, (dk_id,))
            row = cur.fetchone()
            if row is None:
                return None
            status_value = row[0]
            completed_value = row[1]
            return status_value, completed_value
        except sqlite3.Error as err:
            self.logger.error("sqlite error in get_contest_state(): %s", err.args[0])
            return None

    def get_contest_contract_metadata(self, dk_id: int) -> tuple[int | None, int | None, int | None] | None:
        """Fetch metadata needed for canonical contest contract fields."""
        cur = self.conn.cursor()
        try:
            sql = "SELECT total_prizes, max_entry_count, entries FROM contests WHERE dk_id=? LIMIT 1"
            cur.execute(sql, (dk_id,))
            row = cur.fetchone()
            if row is None:
                return None
            total_prizes = row[0]
            max_entry_count = row[1]
            entries = row[2]
            return total_prizes, max_entry_count, entries
        except sqlite3.Error as err:
            self.logger.error("sqlite error in get_contest_contract_metadata(): %s", err.args[0])
            return None

    def get_live_contest_candidates(
        self, sport: str, entry_fee: int = 25, keyword: str = "%", limit: int = 5
    ) -> list[tuple]:
        """
        Get top-N candidate contests for deterministic selection transparency.

        Returns:
            list[tuple]: (dk_id, name, entry_fee, start_date, entries, selection_priority)
        """
        cur = self.conn.cursor()
        try:
            sql = (
                "SELECT dk_id, name, entry_fee, start_date, entries, "
                "       CASE WHEN entry_fee >= ? THEN 0 ELSE 1 END AS selection_priority "
                "FROM contests "
                "WHERE sport=? "
                "  AND name LIKE ? "
                "  AND start_date <= datetime('now', 'localtime') "
                "  AND completed=0 "
                "ORDER BY selection_priority ASC, entry_fee DESC, entries DESC, start_date DESC, dk_id DESC "
                "LIMIT ?"
            )
            cur.execute(sql, (entry_fee, sport, keyword, limit))
            return cur.fetchall()
        except sqlite3.Error as err:
            self.logger.error("sqlite error in get_live_contest_candidates(): %s", err.args[0])
            return []
