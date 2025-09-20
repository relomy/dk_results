import logging
import logging.config
import sqlite3

from classes.draftkings import Draftkings

# load the logging configuration
logging.config.fileConfig("logging.ini")
logger = logging.getLogger(__name__)

# constants
COMPLETED_STATUSES = ["COMPLETED", "CANCELLED"]


def check_contests_for_completion(conn) -> None:
    """Check each contest for completion/positions_paid data."""
    incomplete_contests = db_get_incomplete_contests(conn)

    # if there are no incomplete contests, return
    if not incomplete_contests:
        return

    logger.debug("found %i incomplete contests", len(incomplete_contests))

    skip_draft_groups = []

    for (
        dk_id,
        draft_group,
        entries,
        positions_paid,
        status,
        completed,
        name,
        start_date,
    ) in incomplete_contests:
        if positions_paid is not None and draft_group in skip_draft_groups:
            logger.debug("dk_id: {} positions_paid: {}".format(dk_id, positions_paid))
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
                f"existing: status: {status} entries: {entries} positions_paid: {positions_paid}"
            )
            logger.debug(contest_data)

            # if contest data is different, update it
            if (
                positions_paid != contest_data["positions_paid"]
                or status != contest_data["status"]
                or completed != contest_data["completed"]
            ):
                #            logger.debug("trying to update contest %i", dk_id)
                db_update_contest(
                    conn,
                    [
                        contest_data["positions_paid"],
                        contest_data["status"],
                        contest_data["completed"],
                        dk_id,
                    ],
                )
            else:
                # if contest data is the same, don't update other contests in the same draft group
                skip_draft_groups.append(draft_group)
                logger.debug("contest data is the same, not updating")
        except Exception as error:
            logger.error(error)


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
            "SELECT dk_id, draft_group, entries, positions_paid, status, completed, name, start_date "
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
        conn = sqlite3.connect("contests.db")
        check_contests_for_completion(conn)
    except sqlite3.Error as sql_error:
        logger.error(f"SQLite error: {sql_error}")
    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}")


if __name__ == "__main__":
    main()
