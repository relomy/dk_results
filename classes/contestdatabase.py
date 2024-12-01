import logging
import logging.config
import sqlite3

logging.config.fileConfig("logging.ini")


class ContestDatabase:
    def __init__(self, sqlite3_database: str, logger=None):
        self.logger = logger or logging.getLogger(__name__)
        self.conn = sqlite3.connect(sqlite3_database)

    def get_live_contest(self, sport, entry_fee=25, keyword="%"):
        # get cursor
        cur = self.conn.cursor()

        if sport == "PGAShowdown":
            sport = "GOLF"
            keyword = r"PGA %round%"

        try:
            # execute SQL command
            sql = (
                "SELECT dk_id, name, draft_group, positions_paid "
                "FROM contests "
                "WHERE sport=? "
                "  AND name LIKE ? "
                "  AND entry_fee >= ? "
                "  AND start_date <= datetime('now', 'localtime') "
                "  AND completed=0 "
                "ORDER BY entry_fee DESC, entries DESC "
                "LIMIT 1"
            )

            cur.execute(sql, (sport, keyword, entry_fee))

            # fetch rows
            row = cur.fetchone()

            self.logger.debug(f"returning {row}")

            if row:
                return row

            return None

        except sqlite3.Error as err:
            self.logger.error("sqlite error in get_live_contest(): %s", err.args[0])
