import logging
import logging.config
import sqlite3

from classes.contest import Contest

logging.config.fileConfig("logging.ini")


class ContestDatabase:
    def __init__(self, sqlite3_database: str, logger=None):
        self.logger = logger or logging.getLogger(__name__)
        self.conn = sqlite3.connect(sqlite3_database)

    def create_table(self):
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

    def close(self):
        self.conn.close()
