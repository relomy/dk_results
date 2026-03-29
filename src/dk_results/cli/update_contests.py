import argparse
import datetime
import hashlib
import json
import logging
import os
import re
import sqlite3
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import yaml
from dfs_common import contests, state

from dk_results.bot.discord_rest import DiscordRest
from dk_results.classes.draftkings import Draftkings
from dk_results.classes.sport import Sport
from dk_results.config import load_and_apply_settings
from dk_results.logging import configure_logging
from dk_results.paths import repo_file

configure_logging()
logger = logging.getLogger(__name__)

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover

    def load_dotenv(*_args, **_kwargs):
        return False


load_dotenv()
load_and_apply_settings()

# constants
COMPLETED_STATUSES = ["COMPLETED", "CANCELLED"]
DISCORD_NOTIFICATIONS_ENABLED = os.getenv("DISCORD_NOTIFICATIONS_ENABLED", "true")
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")
SHEET_GIDS_FILE = os.getenv("SHEET_GIDS_FILE", str(repo_file("sheet_gids.yaml")))
CONTEST_WARNING_MINUTES = int(os.getenv("CONTEST_WARNING_MINUTES", "25"))
WARNING_SCHEDULE_FILE_ENV = "CONTEST_WARNING_SCHEDULE_FILE"
DEFAULT_WARNING_SCHEDULE_FILE = str(repo_file("contest_warning_schedules.yaml"))
_DEFAULT_WARNING_SCHEDULE = [CONTEST_WARNING_MINUTES]
VIP_PRESENT = "present"
VIP_ABSENT = "absent"
VIP_UNKNOWN = "unknown"
VIP_ABSENT_REFRESH_MINUTES = 10
VIP_ENTRANT_PAGE_LIMIT = 50

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
        logger.warning("DISCORD_BOT_TOKEN or DISCORD_CHANNEL_ID not set; notifications disabled.")
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
    if not path.is_absolute():
        path = repo_file(SHEET_GIDS_FILE)
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
        logger.warning("Dropped %d invalid warning schedule entries for %s.", invalid, key)
    return sorted(normalized)


def _load_warning_schedule_map() -> dict[str, list[int]]:
    """Load per-sport warning schedules from YAML."""
    schedule_path = os.getenv(WARNING_SCHEDULE_FILE_ENV, DEFAULT_WARNING_SCHEDULE_FILE)
    path = Path(schedule_path)
    if not path.is_absolute():
        path = repo_file(schedule_path)
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
    return WARNING_SCHEDULES.get(key) or WARNING_SCHEDULES.get("default", _DEFAULT_WARNING_SCHEDULE)


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
    sheet_part = f"📊 Sheet: [{sport_name}]({sheet_link})" if sheet_link else "📊 Sheet: n/a"
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


def create_vip_presence_table(conn) -> None:
    sql = """
    CREATE TABLE IF NOT EXISTS contest_vip_presence (
        dk_id INTEGER PRIMARY KEY,
        status TEXT NOT NULL,
        checked_at datetime NOT NULL DEFAULT (datetime('now', 'localtime'))
    );
    """
    conn.execute(sql)
    conn.commit()


def db_get_vip_presence(conn, dk_id: int) -> tuple[str, str] | None:
    cur = conn.cursor()
    cur.execute(
        "SELECT status, checked_at FROM contest_vip_presence WHERE dk_id=? LIMIT 1",
        (dk_id,),
    )
    return cur.fetchone()


def db_upsert_vip_presence(conn, dk_id: int, status: str) -> None:
    create_vip_presence_table(conn)
    conn.execute(
        """
        INSERT INTO contest_vip_presence (dk_id, status)
        VALUES (?, ?)
        ON CONFLICT(dk_id) DO UPDATE SET
            status=excluded.status,
            checked_at=datetime('now', 'localtime')
        """,
        (dk_id, status),
    )
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


def _to_decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _is_zero_time_remaining(value: Any) -> bool:
    parsed = _to_decimal(value)
    return parsed is not None and parsed == 0


def _canonical_score_text(value: Any) -> str | None:
    parsed = _to_decimal(value)
    if parsed is None:
        return None
    normalized = parsed.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return f"{normalized:.2f}"


def _vip_key(name: Any) -> str:
    if not isinstance(name, str):
        return ""
    return name.strip().lower()


_ENTRANT_USERNAME_RE = re.compile(r"""data-un\s*=\s*['"]([^'"]+)['"]""", re.IGNORECASE)


def _parse_entrant_usernames(html: str) -> list[str]:
    if not html:
        return []
    return [match.strip().lower() for match in _ENTRANT_USERNAME_RE.findall(html) if match.strip()]


def _entrant_payload_is_ambiguous(html: str, entrants: list[str]) -> bool:
    if entrants:
        return False
    lowered = html.lower()
    return "data-un" in lowered


def _should_refresh_absent(checked_at: str, start_date: str) -> bool:
    def _normalize_local(dt: datetime.datetime) -> datetime.datetime:
        local_tz = datetime.datetime.now().astimezone().tzinfo
        if dt.tzinfo is None:
            return dt.replace(tzinfo=local_tz)
        return dt.astimezone(local_tz)

    checked_dt = _parse_start_date(checked_at)
    start_dt = _parse_start_date(start_date)
    if not checked_dt or not start_dt:
        return True

    checked_local = _normalize_local(checked_dt)
    start_local = _normalize_local(start_dt)
    now_local = datetime.datetime.now(start_local.tzinfo)
    if now_local < start_local:
        return (now_local - checked_local) >= datetime.timedelta(minutes=VIP_ABSENT_REFRESH_MINUTES)
    return False


def _resolve_vip_presence(
    conn,
    *,
    dk: Draftkings,
    dk_id: int,
    start_date: str,
    vip_names: list[str],
) -> str:
    create_vip_presence_table(conn)
    if not vip_names:
        return VIP_UNKNOWN

    vip_keys = {_vip_key(name) for name in vip_names if _vip_key(name)}
    if not vip_keys:
        return VIP_UNKNOWN

    cached = db_get_vip_presence(conn, dk_id)
    if cached:
        cached_status, checked_at = cached
        if cached_status == VIP_PRESENT:
            return VIP_PRESENT
        if cached_status == VIP_ABSENT and not _should_refresh_absent(checked_at, start_date):
            return VIP_ABSENT

    try:
        for page_no in range(1, VIP_ENTRANT_PAGE_LIMIT + 1):
            html = dk.get_contest_entrants_page(dk_id, page_no)
            entrants = _parse_entrant_usernames(html)
            if _entrant_payload_is_ambiguous(html, entrants):
                logger.warning("entrant payload parse ambiguity for dk_id=%s page=%s", dk_id, page_no)
                return VIP_UNKNOWN
            if not entrants:
                db_upsert_vip_presence(conn, dk_id, VIP_ABSENT)
                return VIP_ABSENT
            if any(name in vip_keys for name in entrants):
                db_upsert_vip_presence(conn, dk_id, VIP_PRESENT)
                return VIP_PRESENT
    except Exception:
        logger.warning("VIP presence check failed for dk_id=%s", dk_id, exc_info=True)
        return VIP_UNKNOWN

    logger.info("vip presence page cap hit for dk_id=%s; returning unknown", dk_id)
    return VIP_UNKNOWN


def _load_vips() -> list[str]:
    path = repo_file("vips.yaml")
    if not path.is_file():
        return []
    try:
        data = yaml.safe_load(path.read_text()) or []
    except Exception:
        logger.warning("failed to load vips.yaml from %s", path)
        return []
    if not isinstance(data, list):
        return []
    vips: list[str] = []
    for item in data:
        name = str(item).strip()
        if name:
            vips.append(name)
    return vips


def _leaderboard_cash_value(row: dict[str, Any]) -> Decimal:
    winning_value = _to_decimal(row.get("winningValue"))
    if winning_value is not None:
        return winning_value

    winnings = row.get("winnings")
    if not isinstance(winnings, list):
        return Decimal("0")

    total = Decimal("0")
    for item in winnings:
        if not isinstance(item, dict):
            continue
        description = str(item.get("description", "")).lower()
        if "cash" not in description:
            continue
        cash = _to_decimal(item.get("value"))
        if cash is None:
            continue
        total += cash
    return total


def _soft_finish_eligible(payload: dict[str, Any]) -> bool:
    leader = payload.get("leader")
    last_winning = payload.get("lastWinningEntry")
    leaderboard_rows = payload.get("leaderBoard")
    if not isinstance(leader, dict) or not isinstance(last_winning, dict):
        return False
    if not isinstance(leaderboard_rows, list) or not leaderboard_rows:
        return False
    if not _is_zero_time_remaining(leader.get("timeRemaining")):
        return False
    if not _is_zero_time_remaining(last_winning.get("timeRemaining")):
        return False
    for row in leaderboard_rows:
        if not isinstance(row, dict):
            return False
        if not _is_zero_time_remaining(row.get("timeRemaining")):
            return False
    return True


def _canonical_vips(vips_cashed: list[str]) -> list[str]:
    unique: dict[str, str] = {}
    for name in vips_cashed:
        cleaned = str(name).strip()
        key = _vip_key(cleaned)
        if not key or key in unique:
            continue
        unique[key] = cleaned
    return sorted(unique.values(), key=lambda vip: vip.lower())


def _soft_finish_event_key(
    *,
    sport_name: str,
    dk_id: int,
    top_score: Any,
    cashing_score: Any,
    vips_cashed: list[str],
) -> str:
    vip_key_payload = sorted({_vip_key(name) for name in vips_cashed if _vip_key(name)})
    payload = {
        "sport": sport_name.upper(),
        "dk_id": int(dk_id),
        "top_score": _canonical_score_text(top_score),
        "cashing_score": _canonical_score_text(cashing_score),
        "vips_cashed": vip_key_payload,
    }
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    return f"soft_finish:{digest}"


def _format_soft_finish_announcement(
    *,
    sport_name: str,
    contest_name: str,
    start_date: str,
    dk_id: int,
    top_score: str,
    cashing_score: str,
    vips_cashed: list[str],
) -> str:
    vip_text = ", ".join(vips_cashed) if vips_cashed else "none"
    base = _format_contest_announcement(
        "Contest soft-finished",
        sport_name,
        contest_name,
        start_date,
        dk_id,
    )
    return "\n".join(
        [
            base,
            f"• 🏆 Top score: {top_score}",
            f"• 💵 Cashing score: {cashing_score}",
            f"• ⭐ VIPs cashed (visible rows): {vip_text}",
        ]
    )


def _maybe_send_soft_finish_announcement(
    conn,
    sender: DiscordRest,
    *,
    sport_name: str,
    contest_name: str,
    start_date: str,
    dk_id: int,
) -> None:
    leaderboard_payload = Draftkings().get_leaderboard(dk_id)
    if not _soft_finish_eligible(leaderboard_payload):
        return

    leader = leaderboard_payload.get("leader", {})
    last_winning = leaderboard_payload.get("lastWinningEntry", {})
    top_score_raw = leader.get("fantasyPoints")
    cashing_score_raw = last_winning.get("fantasyPoints")
    top_score = _canonical_score_text(top_score_raw)
    cashing_score = _canonical_score_text(cashing_score_raw)
    if top_score is None or cashing_score is None:
        return

    vip_keys = {_vip_key(name) for name in _load_vips() if _vip_key(name)}
    cashed_lookup: dict[str, str] = {}
    for row in leaderboard_payload.get("leaderBoard", []):
        if not isinstance(row, dict):
            continue
        username_raw = row.get("userName")
        username = str(username_raw).strip() if username_raw is not None else ""
        key = _vip_key(username)
        if not key or key not in vip_keys:
            continue
        if _leaderboard_cash_value(row) <= 0:
            continue
        if key not in cashed_lookup:
            cashed_lookup[key] = username
    vips_cashed = _canonical_vips(list(cashed_lookup.values()))

    event_key = _soft_finish_event_key(
        sport_name=sport_name,
        dk_id=dk_id,
        top_score=top_score,
        cashing_score=cashing_score,
        vips_cashed=vips_cashed,
    )
    if db_has_notification(conn, dk_id, event_key):
        return

    message = _format_soft_finish_announcement(
        sport_name=sport_name,
        contest_name=contest_name,
        start_date=start_date,
        dk_id=dk_id,
        top_score=top_score,
        cashing_score=cashing_score,
        vips_cashed=vips_cashed,
    )
    sender.send_message(message)
    db_insert_notification(conn, dk_id, event_key)


def check_contests_for_completion(conn) -> None:
    """Check each contest for completion/positions_paid data."""
    create_notifications_table(conn)
    create_vip_presence_table(conn)
    sender = _build_discord_sender()
    dk_client: Draftkings | None = None
    vip_names: list[str] = []
    if sender:
        vip_names = _load_vips()
        try:
            dk_client = Draftkings()
        except Exception:
            logger.warning(
                "VIP presence checks disabled; Draftkings client initialization failed",
                exc_info=True,
            )

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
                if not (now < start_dt <= now + datetime.timedelta(minutes=warning_minutes)):
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
                vip_presence = VIP_UNKNOWN
                if dk_client is not None:
                    vip_presence = _resolve_vip_presence(
                        conn,
                        dk=dk_client,
                        dk_id=dk_id,
                        start_date=str(start_date),
                        vip_names=vip_names,
                    )
                if vip_presence == VIP_ABSENT:
                    logger.info(
                        "skipping warning notification for %s dk_id=%s (%sm); vip_presence=absent",
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
            if positions_paid != contest_data["positions_paid"] or status != new_status or completed != new_completed:
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
                is_new_completed = (status not in COMPLETED_STATUSES and new_status in COMPLETED_STATUSES) or (
                    completed == 0 and new_completed == 1
                )

                if is_new_live and is_primary_live:
                    logger.info(
                        "live transition detected for %s dk_id=%s",
                        sport_name,
                        dk_id,
                    )
                if is_new_live and is_primary_live and not db_has_notification(conn, dk_id, "live"):
                    vip_presence = VIP_UNKNOWN
                    if dk_client is not None:
                        vip_presence = _resolve_vip_presence(
                            conn,
                            dk=dk_client,
                            dk_id=dk_id,
                            start_date=str(start_date),
                            vip_names=vip_names,
                        )
                    if vip_presence == VIP_ABSENT:
                        logger.info(
                            "skipping live notification for %s dk_id=%s; vip_presence=absent",
                            sport_name,
                            dk_id,
                        )
                        continue
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
                    if db_has_notification(conn, dk_id, "live") and not db_has_notification(conn, dk_id, "completed"):
                        vip_presence = VIP_UNKNOWN
                        if dk_client is not None:
                            vip_presence = _resolve_vip_presence(
                                conn,
                                dk=dk_client,
                                dk_id=dk_id,
                                start_date=str(start_date),
                                vip_names=vip_names,
                            )
                        if vip_presence == VIP_ABSENT:
                            logger.info(
                                "skipping completed notification for %s dk_id=%s; vip_presence=absent",
                                sport_name,
                                dk_id,
                            )
                            continue
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

    if sender:
        for sport_cls in sport_choices.values():
            live_row = db_get_live_contest(
                conn,
                sport_cls.name,
                sport_cls.sheet_min_entry_fee,
                sport_cls.keyword,
            )
            if not live_row:
                continue
            live_dk_id, live_contest_name, _live_draft_group, _live_positions_paid, live_start_date = live_row
            contest_state = get_contest_data(live_dk_id)
            if not isinstance(contest_state, dict):
                continue

            state_status = contest_state.get("status")
            state_completed = contest_state.get("completed")
            if not isinstance(state_status, str):
                continue
            if type(state_completed) is not int:
                continue
            if state_status != "LIVE" or state_completed != 0:
                continue

            try:
                _maybe_send_soft_finish_announcement(
                    conn,
                    sender,
                    sport_name=sport_cls.name,
                    contest_name=str(live_contest_name),
                    start_date=str(live_start_date),
                    dk_id=int(live_dk_id),
                )
            except Exception:
                logger.warning(
                    "soft-finish evaluation failed for %s dk_id=%s",
                    sport_cls.name,
                    live_dk_id,
                    exc_info=True,
                )


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


def db_get_live_contest(conn, sport: str, entry_fee: int = 25, keyword: str = "%") -> tuple | None:
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
        logger.error(f"sqlite error [check_db_contests_for_completion()]: {err.args[0]}")

    return None


def db_get_next_upcoming_contest(conn, sport: str, entry_fee: int = 25, keyword: str = "%") -> tuple | None:
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
        logger.error("sqlite error in db_get_next_upcoming_contest_any(): %s", err.args[0])
        return None


def _build_parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(description="Update contest completion state and send contest status notifications.")


def main(argv: list[str] | None = None):
    argv_list = list(argv) if argv is not None else []
    _build_parser().parse_args(argv_list)
    configure_logging()
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
