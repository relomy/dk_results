import datetime
import logging
import logging.config
import os
import sqlite3
from pathlib import Path
from typing import Any

from dfs_common import contests, state
import yaml

from bot.discord_rest import DiscordRest
from classes.draftkings import Draftkings
from classes.sport import Sport

# load the logging configuration
logging.config.fileConfig("logging.ini")
logger = logging.getLogger(__name__)

# constants
COMPLETED_STATUSES = ["COMPLETED", "CANCELLED"]
DISCORD_NOTIFICATIONS_ENABLED = os.getenv("DISCORD_NOTIFICATIONS_ENABLED", "true")
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")
SHEET_GIDS_FILE = os.getenv("SHEET_GIDS_FILE", "sheet_gids.yaml")
CONTEST_WARNING_MINUTES = int(os.getenv("CONTEST_WARNING_MINUTES", "25"))
WARNING_SCHEDULE_FILE_ENV = "CONTEST_WARNING_SCHEDULE_FILE"
DEFAULT_WARNING_SCHEDULE_FILE = "contest_warning_schedules.yaml"
_DEFAULT_WARNING_SCHEDULE = [CONTEST_WARNING_MINUTES]

SPORT_EMOJI = {
    "CFB": "🏈",
    "GOLF": "⛳",
    "LOL": "🎮",
    "MLB": "⚾",
    "MMA": "🥊",
    "NAS": "🏎️",
    "NBA": "🏀",
    "NFL": "🏈",
    "NFLAfternoon": "🏈",
    "NFLShowdown": "🏈",
    "NHL": "🏒",
    "PGAMain": "⛳",
    "PGAShowdown": "⛳",
    "PGAWeekend": "⛳",
    "SOC": "⚽",
    "TEN": "🎾",
    "USFL": "🏈",
    "XFL": "🏈",
}


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


def _load_sheet_gid_map() -> dict[str, int]:
    if not SHEET_GIDS_FILE:
        return {}
    path = Path(SHEET_GIDS_FILE)
    if not path.is_file():
        return {}
    try:
        data = yaml.safe_load(path.read_text()) or {}
    except Exception:
        logger.warning("Failed to load sheet gid map from %s", path)
        return {}
    if not isinstance(data, dict):
        return {}
    gids: dict[str, int] = {}
    for key, value in data.items():
        if isinstance(key, str) and isinstance(value, int):
            gids[key] = value
    return gids


SHEET_GID_MAP = _load_sheet_gid_map()


def _normalize_warning_schedule(items: Any, *, key: str) -> list[int]:
    """Normalize a schedule list, logging and dropping invalid entries."""
    if not isinstance(items, list):
        logger.warning("Invalid warning schedule for %s; expected list.", key)
        return []
    normalized: set[int] = set()
    invalid = 0
    for item in items:
        if isinstance(item, int) and item > 0:
            normalized.add(item)
        else:
            invalid += 1
    if invalid:
        logger.warning(
            "Dropped %d invalid warning schedule entries for %s.", invalid, key
        )
    return sorted(normalized)


def _load_warning_schedule_map() -> dict[str, list[int]]:
    """Load per-sport warning schedules from YAML."""
    schedule_path = os.getenv(WARNING_SCHEDULE_FILE_ENV, DEFAULT_WARNING_SCHEDULE_FILE)
    path = Path(schedule_path)
    if not path.is_file():
        return {"default": _DEFAULT_WARNING_SCHEDULE}
    try:
        data = yaml.safe_load(path.read_text()) or {}
    except Exception:
        logger.warning("Failed to load warning schedules from %s", path)
        return {"default": _DEFAULT_WARNING_SCHEDULE}
    if not isinstance(data, dict):
        logger.warning("Warning schedule file at %s did not contain a dict.", path)
        return {"default": _DEFAULT_WARNING_SCHEDULE}
    schedules: dict[str, list[int]] = {}
    for key, value in data.items():
        if not isinstance(key, str) or not key:
            logger.warning("Ignoring invalid warning schedule key: %s", key)
            continue
        normalized = _normalize_warning_schedule(value, key=key)
        if normalized:
            schedules[key.lower()] = normalized
    if "default" not in schedules:
        schedules["default"] = _DEFAULT_WARNING_SCHEDULE
    return schedules


WARNING_SCHEDULES = _load_warning_schedule_map()


def _warning_schedule_for(sport_name: str) -> list[int]:
    """Return warning schedule for a sport, falling back to default."""
    key = sport_name.lower()
    return WARNING_SCHEDULES.get(key) or WARNING_SCHEDULES.get(
        "default", _DEFAULT_WARNING_SCHEDULE
    )


def _sheet_link(sheet_title: str) -> str | None:
    if not SPREADSHEET_ID:
        return None
    gid = SHEET_GID_MAP.get(sheet_title)
    if gid is None:
        return None
    return f"<https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/edit#gid={gid}>"


def _sport_emoji(sport_name: str) -> str:
    return SPORT_EMOJI.get(sport_name, "🏟️")


def _format_contest_announcement(
    prefix: str,
    sport_name: str,
    contest_name: str,
    start_date: str,
    dk_id: int,
) -> str:
    url = _contest_url(dk_id)
    sheet_link = _sheet_link(sport_name)
    sheet_part = (
        f"📊 Sheet: [{sport_name}]({sheet_link})" if sheet_link else "📊 Sheet: n/a"
    )
    relative = None
    start_dt = _parse_start_date(start_date)
    if start_dt:
        delta = start_dt - datetime.datetime.now(start_dt.tzinfo)
        if delta.total_seconds() > 0:
            seconds = int(delta.total_seconds())
            minutes, sec = divmod(seconds, 60)
            hours, minutes = divmod(minutes, 60)
            days, hours = divmod(hours, 24)
            parts = []
            if days:
                parts.append(f"{days}d")
            if hours:
                parts.append(f"{hours}h")
            if minutes:
                parts.append(f"{minutes}m")
            if not parts:
                parts.append(f"{sec}s")
            relative = "".join(parts)
    relative_part = f" (⏳ {relative})" if relative else ""
    return "\n".join(
        [
            f"{prefix}: {_sport_emoji(sport_name)} {sport_name} — {contest_name}",
            f"• 🕒 {start_date}{relative_part}",
            f"• 🔗 DK: [{dk_id}]({url})",
            f"• {sheet_part}",
        ]
    )


def _contests_db_path() -> str:
    return str(state.contests_db_path())


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
    try:
        create_notifications_table(conn)
        cur = conn.cursor()
        cur.execute(
            "INSERT OR IGNORE INTO contest_notifications (dk_id, event) VALUES (?, ?)",
            (dk_id, event),
        )
        conn.commit()
    except (sqlite3.Error, AttributeError) as err:
        logger.error("sqlite error inserting notification: %s", err)


def _contest_url(dk_id: int) -> str:
    return f"<https://www.draftkings.com/contest/gamecenter/{dk_id}#/>"


def _parse_start_date(start_date: Any) -> datetime.datetime | None:
    if not start_date:
        return None
    if isinstance(start_date, datetime.datetime):
        return start_date
    try:
        return datetime.datetime.fromisoformat(str(start_date))
    except (TypeError, ValueError):
        return None


def check_contests_for_completion(conn) -> None:
    """Check each contest for completion/positions_paid data."""
    create_notifications_table(conn)
    sender = _build_discord_sender()

    if sender:
        logged_schedules: set[str] = set()
        for sport_cls in _sport_choices().values():
            upcoming_match = db_get_next_upcoming_contest(
                conn,
                sport_cls.name,
                sport_cls.sheet_min_entry_fee,
                sport_cls.keyword,
            )
            upcoming_any = db_get_next_upcoming_contest_any(conn, sport_cls.name)
            row = upcoming_match or upcoming_any
            if not row:
                continue
            dk_id, name, _draft_group, _positions_paid, start_date = row
            start_dt = _parse_start_date(start_date)
            if not start_dt:
                continue
            now = datetime.datetime.now(start_dt.tzinfo)
            # This script runs every 10 minutes via cron, so warnings use windows
            # rather than requiring an exact timestamp match.
            schedule = _warning_schedule_for(sport_cls.name)
            schedule_key = sport_cls.name.lower()
            if schedule_key not in logged_schedules:
                source = "sport" if schedule_key in WARNING_SCHEDULES else "default"
                logger.debug(
                    "warning schedule for %s: %s (source=%s)",
                    sport_cls.name,
                    schedule,
                    source,
                )
                logged_schedules.add(schedule_key)
            for warning_minutes in schedule:
                if not (
                    now < start_dt <= now + datetime.timedelta(minutes=warning_minutes)
                ):
                    continue
                warning_key = f"warning:{warning_minutes}"
                if db_has_notification(conn, dk_id, warning_key):
                    logger.debug(
                        "warning already sent for %s dk_id=%s (%sm)",
                        sport_cls.name,
                        dk_id,
                        warning_minutes,
                    )
                    continue
                message = _format_contest_announcement(
                    f"Contest starting soon ({warning_minutes}m)",
                    sport_cls.name,
                    name,
                    str(start_date),
                    dk_id,
                )
                logger.info(
                    "sending warning notification for %s dk_id=%s (%sm)",
                    sport_cls.name,
                    dk_id,
                    warning_minutes,
                )
                sender.send_message(message)
                db_insert_notification(conn, dk_id, warning_key)
                logger.info(
                    "warning notification stored for %s dk_id=%s (%sm)",
                    sport_cls.name,
                    dk_id,
                    warning_minutes,
                )

    incomplete_contests = db_get_incomplete_contests(conn)

    # if there are no incomplete contests, return
    if not incomplete_contests:
        return

    logger.debug("found %i incomplete contests", len(incomplete_contests))

    skip_draft_groups = []
    sport_choices = _sport_choices()

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
                live_row = db_get_live_contest(
                    conn,
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

                if is_new_live and is_primary_live:
                    logger.info(
                        "live transition detected for %s dk_id=%s",
                        sport_name,
                        dk_id,
                    )
                if (
                    is_new_live
                    and is_primary_live
                    and not db_has_notification(conn, dk_id, "live")
                ):
                    message = _format_contest_announcement(
                        "Contest started",
                        sport_name,
                        name,
                        str(start_date),
                        dk_id,
                    )
                    logger.info(
                        "sending live notification for %s dk_id=%s",
                        sport_name,
                        dk_id,
                    )
                    sender.send_message(message)
                    db_insert_notification(conn, dk_id, "live")
                    logger.info(
                        "live notification stored for %s dk_id=%s",
                        sport_name,
                        dk_id,
                    )
                elif is_new_live and is_primary_live:
                    logger.info(
                        "live notification already sent for %s dk_id=%s",
                        sport_name,
                        dk_id,
                    )

                if is_new_completed:
                    if db_has_notification(
                        conn, dk_id, "live"
                    ) and not db_has_notification(conn, dk_id, "completed"):
                        message = _format_contest_announcement(
                            "Contest ended",
                            sport_name,
                            name,
                            str(start_date),
                            dk_id,
                        )
                        logger.info(
                            "sending completed notification for %s dk_id=%s",
                            sport_name,
                            dk_id,
                        )
                        sender.send_message(message)
                        db_insert_notification(conn, dk_id, "completed")
                        logger.info(
                            "completed notification stored for %s dk_id=%s",
                            sport_name,
                            dk_id,
                        )
                    elif db_has_notification(conn, dk_id, "completed"):
                        logger.info(
                            "completed notification already sent for %s dk_id=%s",
                            sport_name,
                            dk_id,
                        )
                    elif not db_has_notification(conn, dk_id, "live"):
                        logger.info(
                            "skipping completed notification for %s dk_id=%s; live notification missing",
                            sport_name,
                            dk_id,
                        )
        except Exception as error:
            logger.error(error)


def get_contest_data(dk_id) -> dict | None:
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
    except ValueError as val_err:
        logger.error(f"JSON decoding error: {val_err}")
    except KeyError as key_err:
        logger.error(f"Key error: {key_err}")
    except Exception as req_ex:
        logger.error(f"Request error: {req_ex}")

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


def db_get_live_contest(
    conn, sport: str, entry_fee: int = 25, keyword: str = "%"
) -> tuple | None:
    """Get a live contest matching the criteria."""
    cur = conn.cursor()
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
            logger.debug("returning %s", row)
            return row

        cur.execute(base_sql + "  AND entry_fee < ?" + ordering, (sport, keyword, entry_fee))
        row = cur.fetchone()
        if row:
            logger.debug("returning %s", row)
        return row
    except sqlite3.Error as err:
        logger.error("sqlite error in db_get_live_contest(): %s", err.args[0])
        return None


def db_get_incomplete_contests(conn):
    """Get the incomplete contests from the database."""
    try:
        # get cursor
        cur = conn.cursor()

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


def db_get_next_upcoming_contest(
    conn, sport: str, entry_fee: int = 25, keyword: str = "%"
) -> tuple | None:
    """Get the next upcoming contest matching criteria."""
    try:
        cur = conn.cursor()
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
        if row is not None:
            logger.debug("returning %s", row)
        return row if row else None
    except sqlite3.Error as err:
        logger.error("sqlite error in db_get_next_upcoming_contest(): %s", err.args[0])
        return None


def db_get_next_upcoming_contest_any(conn, sport: str) -> tuple | None:
    """Get the next upcoming contest for a sport, regardless of criteria."""
    try:
        cur = conn.cursor()
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
        if row is not None:
            logger.debug("returning %s", row)
        return row if row else None
    except sqlite3.Error as err:
        logger.error(
            "sqlite error in db_get_next_upcoming_contest_any(): %s", err.args[0]
        )
        return None


def main():
    try:
        contests.init_schema(state.contests_db_path())
        conn = sqlite3.connect(_contests_db_path())
        check_contests_for_completion(conn)
    except sqlite3.Error as sql_error:
        logger.error(f"SQLite error: {sql_error}")
    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}")


if __name__ == "__main__":
    main()
