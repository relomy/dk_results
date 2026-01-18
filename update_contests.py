import logging
import logging.config
import os
import sqlite3

from bot.discord_rest import DiscordRest
from classes.contestdatabase import ContestDatabase
from classes.draftkings import Draftkings
from classes.sport import Sport

# load the logging configuration
logging.config.fileConfig("logging.ini")
logger = logging.getLogger(__name__)

# constants
COMPLETED_STATUSES = ["COMPLETED", "CANCELLED"]
DB_FILE = os.getenv("CONTESTS_DB_PATH", "contests.db")
DISCORD_NOTIFICATIONS_ENABLED = os.getenv("DISCORD_NOTIFICATIONS_ENABLED", "true")


def _is_notifications_enabled() -> bool:
    return DISCORD_NOTIFICATIONS_ENABLED.strip().lower() not in {"0", "false", "no"}


def _sport_choices() -> dict[str, type[Sport]]:
    choices: dict[str, type[Sport]] = {}
    for sport in Sport.__subclasses__():
        name = getattr(sport, "name", None)
        if not isinstance(name, str) or not name:
            continue
        choices[name] = sport
    return choices


def _build_discord_sender() -> DiscordRest | None:
    if not _is_notifications_enabled():
        logger.info("Discord notifications disabled via DISCORD_NOTIFICATIONS_ENABLED.")
        return None
    token = os.getenv("DISCORD_BOT_TOKEN")
    channel_id_raw = os.getenv("DISCORD_CHANNEL_ID")
    if not token or not channel_id_raw:
        logger.warning(
            "DISCORD_BOT_TOKEN or DISCORD_CHANNEL_ID not set; notifications disabled."
        )
        return None
    try:
        channel_id = int(channel_id_raw)
    except ValueError:
        logger.warning("DISCORD_CHANNEL_ID is not a valid integer: %s", channel_id_raw)
        return None
    return DiscordRest(token, channel_id)


def create_notifications_table(conn) -> None:
    sql = """
    CREATE TABLE IF NOT EXISTS contest_notifications (
        dk_id INTEGER NOT NULL,
        event TEXT NOT NULL,
        announced_at datetime NOT NULL DEFAULT (datetime('now', 'localtime')),
        PRIMARY KEY (dk_id, event)
    );
    """
    conn.execute(sql)
    conn.commit()


def db_has_notification(conn, dk_id: int, event: str) -> bool:
    cur = conn.cursor()
    cur.execute(
        "SELECT 1 FROM contest_notifications WHERE dk_id=? AND event=? LIMIT 1",
        (dk_id, event),
    )
    return cur.fetchone() is not None


def db_insert_notification(conn, dk_id: int, event: str) -> None:
    cur = conn.cursor()
    try:
        cur.execute(
            "INSERT OR IGNORE INTO contest_notifications (dk_id, event) VALUES (?, ?)",
            (dk_id, event),
        )
        conn.commit()
    except sqlite3.Error as err:
        logger.error("sqlite error inserting notification: %s", err.args[0])


def _contest_url(dk_id: int) -> str:
    return f"https://www.draftkings.com/contest/gamecenter/{dk_id}#/"


def check_contests_for_completion(conn) -> None:
    """Check each contest for completion/positions_paid data."""
    create_notifications_table(conn)
    incomplete_contests = db_get_incomplete_contests(conn)

    # if there are no incomplete contests, return
    if not incomplete_contests:
        return

    logger.debug("found %i incomplete contests", len(incomplete_contests))

    skip_draft_groups = []
    sender = _build_discord_sender()
    contest_db = ContestDatabase(DB_FILE, logger=logger)
    sport_choices = _sport_choices()

    try:
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
            if positions_paid is not None and draft_group in skip_draft_groups:
                logger.debug(
                    "dk_id: {} positions_paid: {}".format(dk_id, positions_paid)
                )
                logger.debug(
                    "skipping %s because we've already updated %d [skipped draft groups %s]",
                    name,
                    draft_group,
                    " ".join(str(dg) for dg in skip_draft_groups),
                )
                continue

            # navigate to the gamecenter URL
            logger.debug(
                "getting contest data for %s [id: %i start: %s dg: %d]",
                name,
                dk_id,
                start_date,
                draft_group,
            )

            try:
                contest_data = get_contest_data(dk_id)

                if contest_data is None:
                    continue

                logger.debug(
                    "existing: status: %s entries: %s positions_paid: %s",
                    status,
                    entries,
                    positions_paid,
                )
                logger.debug(contest_data)

                new_status = contest_data["status"]
                new_completed = contest_data["completed"]

                # if contest data is different, update it
                if (
                    positions_paid != contest_data["positions_paid"]
                    or status != new_status
                    or completed != new_completed
                ):
                    db_update_contest(
                        conn,
                        [
                            contest_data["positions_paid"],
                            new_status,
                            new_completed,
                            dk_id,
                        ],
                    )
                else:
                    # if contest data is the same, don't update other contests in the same draft group
                    skip_draft_groups.append(draft_group)
                    logger.debug("contest data is the same, not updating")

                if sender and sport_name in sport_choices:
                    sport_cls = sport_choices[sport_name]
                    live_row = contest_db.get_live_contest(
                        sport_cls.name,
                        sport_cls.sheet_min_entry_fee,
                        sport_cls.keyword,
                    )
                    is_primary_live = bool(live_row and live_row[0] == dk_id)

                    is_new_live = status != "LIVE" and new_status == "LIVE"
                    is_new_completed = (
                        status not in COMPLETED_STATUSES
                        and new_status in COMPLETED_STATUSES
                    ) or (completed == 0 and new_completed == 1)

                    if (
                        is_new_live
                        and is_primary_live
                        and not db_has_notification(conn, dk_id, "live")
                    ):
                        message = (
                            f"Contest started: {sport_name} {name} "
                            f"(dk_id={dk_id}) start={start_date} url={_contest_url(dk_id)}"
                        )
                        sender.send_message(message)
                        db_insert_notification(conn, dk_id, "live")

                    if is_new_completed:
                        if db_has_notification(
                            conn, dk_id, "live"
                        ) and not db_has_notification(conn, dk_id, "completed"):
                            message = (
                                f"Contest ended: {sport_name} {name} "
                                f"(dk_id={dk_id}) start={start_date} url={_contest_url(dk_id)}"
                            )
                            sender.send_message(message)
                            db_insert_notification(conn, dk_id, "completed")
            except Exception as error:
                logger.error(error)
    finally:
        contest_db.close()


def get_contest_data(dk_id) -> dict:
    try:
        dk = Draftkings()
        response_json = dk.get_contest_detail(dk_id)
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
    except Exception as req_ex:
        logger.error(f"Request error: {req_ex}")
    except ValueError as val_err:
        logger.error(f"JSON decoding error: {val_err}")
    except KeyError as key_err:
        logger.error(f"Key error: {key_err}")
    except Exception as ex:
        logger.error(f"An unexpected error occurred: {ex}")

    return None


def db_update_contest(conn, contest_to_update) -> None:
    """Update contest fields based on get_contest_data()."""
    logger.debug("trying to update contest %i", contest_to_update[3])
    cur = conn.cursor()

    sql = "UPDATE contests SET positions_paid=?, status=?, completed=? WHERE dk_id=?"

    try:
        cur.execute(sql, contest_to_update)
        conn.commit()
        logger.info("Total %d records updated successfully!", cur.rowcount)
    except sqlite3.Error as err:
        logger.error("sqlite error: %s", err.args[0])


def db_get_incomplete_contests(conn):
    """Get the incomplete contests from the database."""
    # get cursor
    cur = conn.cursor()

    try:
        # execute SQL command
        sql = (
            "SELECT dk_id, draft_group, entries, positions_paid, status, completed, name, start_date, sport "
            "FROM contests "
            "WHERE start_date <= datetime('now', 'localtime') "
            "  AND (positions_paid IS NULL OR completed = 0)"
        )
        cur.execute(sql)

        # return all rows
        return cur.fetchall()
    except sqlite3.Error as err:
        logger.error(
            f"sqlite error [check_db_contests_for_completion()]: {err.args[0]}"
        )

    return None


def main():
    try:
        conn = sqlite3.connect(DB_FILE)
        check_contests_for_completion(conn)
    except sqlite3.Error as sql_error:
        logger.error(f"SQLite error: {sql_error}")
    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}")


if __name__ == "__main__":
    main()
