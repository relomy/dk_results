import logging
import logging.config
import sqlite3

from classes.contest import Contest

logging.config.fileConfig("logging.ini")


class ContestDatabase:
    def __init__(self, sqlite3_database: str, logger=None) -> None:
        """
        Initialize ContestDatabase with SQLite database file.

        Args:
            sqlite3_database (str): Path to SQLite database file.
            logger (logging.Logger, optional): Logger instance.
        """
        self.logger = logger or logging.getLogger(__name__)
        self.conn = sqlite3.connect(sqlite3_database)

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
        sql = "SELECT dk_id FROM contests WHERE dk_id IN ({})".format(
            ", ".join("?" for _ in dk_ids)
        )
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

    def get_live_contest(
        self, sport: str, entry_fee: int = 25, keyword: str = "%"
    ) -> tuple | None:
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
            self.logger.error("sqlite error in get_live_contest(): %s", err.args[0])

    def get_live_contests(
        self, sports: list[str] | None = None, entry_fee: int = 25, keyword: str = "%"
    ) -> list[tuple]:
        """
        Get all live contests matching the criteria.

        Args:
            sports (list[str] | None): Sport names to include; if None, include all.
            entry_fee (int, optional): Minimum entry fee. Defaults to 25.
            keyword (str, optional): Name keyword pattern. Defaults to "%".

        Returns:
            list[tuple]: Each tuple is (dk_id, name, draft_group, positions_paid, start_date, sport).
        """
        cur = self.conn.cursor()
        try:
            base_sql = (
                "SELECT dk_id, name, draft_group, positions_paid, start_date, sport "
                "FROM contests "
                "WHERE name LIKE ? "
                "  AND entry_fee >= ? "
                "  AND start_date <= datetime('now', 'localtime') "
                "  AND completed=0 "
            )
            params: list = [keyword, entry_fee]
            if sports:
                placeholders = ", ".join("?" for _ in sports)
                base_sql += f" AND sport IN ({placeholders})"
                params.extend(sports)
            base_sql += " ORDER BY sport, entry_fee DESC, entries DESC"

            cur.execute(base_sql, params)
            rows = cur.fetchall()
            self.logger.debug("returning %d live contests", len(rows))
            return rows or []
        except sqlite3.Error as err:
            self.logger.error("sqlite error in get_live_contests(): %s", err.args[0])
            return []
