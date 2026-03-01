"""Raw single-contest collector for snapshot v3."""

from __future__ import annotations

import datetime
import hashlib
import logging
import os
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo

from dfs_common import state

from dk_results.classes.contestdatabase import ContestDatabase
from dk_results.classes.draftkings import Draftkings
from dk_results.classes.results import Results
from dk_results.classes.sport import Sport
from dk_results.classes.trainfinder import TrainFinder
from dk_results.paths import repo_file
from dk_results.services.snapshot_v3.constants import DEFAULT_STANDINGS_LIMIT
from dk_results.services.snapshot_v3.normalize import (
    is_live_from_slot,
    normalize_name,
    slug,
    to_float,
    to_utc_iso,
)
from dk_results.services.vips import load_vips

logger = logging.getLogger(__name__)

CONTEST_DIR = str(repo_file("contests"))
SALARY_DIR = str(repo_file("salary"))
SALARY_LIMIT = 40000
COOKIES_FILE = str(repo_file("pickled_cookies_works.txt"))
CANDIDATE_LIMIT = 5


def _sport_choices() -> dict[str, type[Sport]]:
    return {sport.name.upper(): sport for sport in Sport.__subclasses__()}


def _rank_numeric(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        text = str(value).strip().upper()
        if text.startswith("T"):
            try:
                return int(text[1:])
            except ValueError:
                return None
    return None


def _ownership_remaining_for_user(user: Any) -> float | None:
    lineup_obj = getattr(user, "lineupobj", None)
    if not lineup_obj:
        return None
    total = 0.0
    has_any = False
    for player in getattr(lineup_obj, "lineup", []):
        if getattr(player, "game_info", "") == "Final":
            continue
        ownership = getattr(player, "ownership", None)
        if ownership in (None, ""):
            continue
        has_any = True
        total += float(ownership) * 100
    if not has_any:
        return 0.0
    return total


def _avg_salary_per_player_remaining(users: list[Any]) -> float | None:
    total_salary = 0.0
    remaining_slots = 0
    saw_any_slot = False
    for user in users:
        lineup_obj = getattr(user, "lineupobj", None)
        if not lineup_obj:
            continue
        for player in getattr(lineup_obj, "lineup", []):
            saw_any_slot = True
            if str(getattr(player, "game_info", "")).strip() == "Final":
                continue
            salary = to_float(getattr(player, "salary", None))
            if not isinstance(salary, (int, float)):
                continue
            total_salary += float(salary)
            remaining_slots += 1

    if remaining_slots > 0:
        return total_salary / float(remaining_slots)
    if saw_any_slot:
        return 0.0
    return None


def _lineup_signature(user: Any) -> str:
    lineup_obj = getattr(user, "lineupobj", None)
    if not lineup_obj:
        return ""
    names = [getattr(player, "name", "").strip() for player in lineup_obj.lineup]
    return "|".join(names)


def _cluster_id_from_signature(signature: str) -> str:
    return hashlib.sha1(signature.encode("utf-8")).hexdigest()[:12]


def _build_selection_reason(
    *,
    mode: str,
    sport: str,
    min_entry_fee: int,
    keyword: str,
    selected_from_candidate_count: int,
    contest_id: int | None = None,
) -> dict[str, Any]:
    criteria: dict[str, Any] = {
        "sport": sport,
        "min_entry_fee": min_entry_fee,
        "keyword": keyword,
        "status_window": "start_date <= now && completed=0",
        "primary_preference": "entry_fee >= min_entry_fee then fallback below min",
    }
    if mode == "explicit_id":
        criteria = {"contest_id": str(contest_id) if contest_id is not None else None}

    return {
        "mode": mode,
        "criteria": criteria,
        "tie_breakers": [
            "entry_fee desc",
            "entries desc",
            "start_date desc",
            "dk_id desc",
        ],
        "selected_from_candidate_count": selected_from_candidate_count,
    }


def _summarize_candidates(rows: list[tuple], top_n: int = CANDIDATE_LIMIT) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for row in rows:
        contest_id, name, entry_fee, start_date, entries, selection_priority = row
        normalized.append(
            {
                "contest_id": str(contest_id),
                "name": name,
                "entry_fee": entry_fee,
                "entries": entries,
                "start_time_utc": to_utc_iso(start_date),
                "selection_priority": int(selection_priority),
            }
        )

    normalized.sort(
        key=lambda item: (
            item["selection_priority"],
            -int(item["entry_fee"] or 0),
            -int(item["entries"] or 0),
            item["contest_id"],
        )
    )
    return normalized[:top_n]


def _first_not_blank(*values: Any) -> Any:
    for value in values:
        if value not in (None, ""):
            return value
    return None


def _contest_row_from_detail(dk_id: int, detail: dict[str, Any]) -> tuple:
    contest_detail = detail.get("contestDetail", {})
    payout_summary = contest_detail.get("payoutSummary") or []
    positions_paid = None
    if payout_summary:
        positions_paid = payout_summary[0].get("maxPosition")
    start_time = contest_detail.get("contestStartTime")
    prize_pool = _first_not_blank(
        contest_detail.get("totalPrizePool"),
        contest_detail.get("totalPrizes"),
        contest_detail.get("totalPayouts"),
        contest_detail.get("totalPayout"),
        contest_detail.get("prizePool"),
        contest_detail.get("payout"),
    )
    max_entries_per_user = _first_not_blank(
        contest_detail.get("maxEntriesPerUser"),
        contest_detail.get("maximumEntriesPerUser"),
        contest_detail.get("maxEntriesPerPerson"),
        contest_detail.get("maxEntryCount"),
    )
    return (
        dk_id,
        contest_detail.get("name"),
        contest_detail.get("draftGroupId"),
        positions_paid,
        start_time,
        contest_detail.get("entryFee"),
        contest_detail.get("maximumEntries"),
        contest_detail.get("contestState") or contest_detail.get("contestStatus"),
        contest_detail.get("isCompleted"),
        prize_pool,
        max_entries_per_user,
    )


def _dollars_to_cents_half_up(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    cents = (amount * Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    try:
        return int(cents)
    except (TypeError, ValueError):
        return None


def _leaderboard_row_payout_cents(row: dict[str, Any]) -> int | None:
    candidates = (
        row.get("winningValue"),
        row.get("winnings"),
        row.get("payout"),
        row.get("cash"),
    )
    for candidate in candidates:
        cents = _dollars_to_cents_half_up(candidate)
        if cents is not None:
            return cents
    return None


def _leaderboard_payout_map(payload: dict[str, Any]) -> dict[str, int]:
    results: dict[str, int] = {}
    rows = payload.get("contestStandings")
    if not isinstance(rows, list):
        rows = payload.get("standings")
    if not isinstance(rows, list):
        return results
    for row in rows:
        if not isinstance(row, dict):
            continue
        entry_key = row.get("entryKey") or row.get("entryId") or row.get("entry_id")
        if entry_key in (None, ""):
            continue
        payout_cents = _leaderboard_row_payout_cents(row)
        if payout_cents is None:
            continue
        results[str(entry_key)] = payout_cents
    return results


def _normalize_contest_state(raw_state: Any, completed: Any) -> str | None:
    if completed in (1, True, "1", "true", "True"):
        return "completed"
    text = str(raw_state or "").strip().lower()
    if not text:
        return None
    if text in {"live", "in progress", "in_progress", "started"}:
        return "live"
    if text in {"completed", "complete", "final"}:
        return "completed"
    if text in {"cancelled", "canceled"}:
        return "cancelled"
    if text in {"scheduled", "upcoming", "open"}:
        return "upcoming"
    return None


def _derive_composite_player_key(sport: str, row: dict[str, Any]) -> str | None:
    name_slug = slug(row.get("name") or row.get("player_name"))
    if not name_slug:
        return None
    team_slug = slug(row.get("team") or row.get("team_abbv")) or "na"
    pos_slug = slug(row.get("position") or row.get("pos")) or "na"
    salary_num = to_float(row.get("salary"))
    salary_part = str(int(round(salary_num))) if salary_num is not None else "na"
    return f"{sport.lower()}:{name_slug}:{team_slug}:{salary_part}:{pos_slug}"


def _normalize_players(
    raw_players: list[Any],
    sport: str,
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    normalized_players: list[dict[str, Any]] = []
    keys_by_name: dict[str, set[str]] = {}

    for row in raw_players:
        if not isinstance(row, dict):
            continue
        mapped = dict(row)
        player_key = row.get("player_key")
        if player_key in (None, ""):
            player_key = _derive_composite_player_key(sport, row)
        if player_key not in (None, ""):
            mapped["player_key"] = str(player_key)
        normalized_players.append(mapped)

        name_key = normalize_name(mapped.get("name") or mapped.get("player_name"))
        if not name_key:
            continue
        if mapped.get("player_key") in (None, ""):
            continue
        keys_by_name.setdefault(name_key, set()).add(str(mapped.get("player_key")))

    unique_name_to_key: dict[str, str] = {}
    for name_key, keys in keys_by_name.items():
        if len(keys) == 1:
            unique_name_to_key[name_key] = next(iter(keys))

    return normalized_players, unique_name_to_key


def _normalize_vip_lineup_rows(
    raw_vip_lineups: list[Any],
    standings: list[dict[str, Any]],
    sport: str,
    unique_name_to_player_key: dict[str, str],
) -> list[dict[str, Any]]:
    standings_entry_keys_by_name: dict[str, set[str]] = {}
    for row in standings:
        if not isinstance(row, dict):
            continue
        username = row.get("username")
        entry_key = row.get("entry_key")
        if username in (None, "") or entry_key in (None, ""):
            continue
        standings_entry_keys_by_name.setdefault(str(username).strip().lower(), set()).add(str(entry_key))

    standings_entry_key_by_name = {
        name: next(iter(entry_keys))
        for name, entry_keys in standings_entry_keys_by_name.items()
        if len(entry_keys) == 1
    }

    normalized_rows: list[dict[str, Any]] = []
    for row in raw_vip_lineups:
        if not isinstance(row, dict):
            continue

        display_name = row.get("display_name") or row.get("user") or row.get("username")
        entry_key = row.get("entry_key")
        if entry_key in (None, "") and display_name not in (None, ""):
            entry_key = standings_entry_key_by_name.get(str(display_name).strip().lower())
        vip_entry_key = row.get("vip_entry_key") if row.get("vip_entry_key") not in (None, "") else entry_key

        players_source = row.get("players_live")
        if not isinstance(players_source, list):
            players_source = row.get("lineup")
        if not isinstance(players_source, list):
            players_source = row.get("players")
        if not isinstance(players_source, list):
            players_source = []

        players_live: list[dict[str, Any]] = []
        for slot in players_source:
            if not isinstance(slot, dict):
                continue
            player_name = slot.get("player_name") or slot.get("name")
            if player_name in (None, ""):
                continue
            player_key = slot.get("player_key")
            if player_key in (None, ""):
                player_key = unique_name_to_player_key.get(normalize_name(player_name))
            if player_key in (None, ""):
                player_key = _derive_composite_player_key(
                    sport,
                    {
                        **slot,
                        "player_name": player_name,
                    },
                )
            live_slot: dict[str, Any] = {"player_name": str(player_name)}
            if player_key not in (None, ""):
                live_slot["player_key"] = str(player_key)
            salary = to_float(slot.get("salary"))
            if salary is not None:
                live_slot["salary"] = int(round(salary))
            live_slot["is_live"] = is_live_from_slot(slot)
            players_live.append(live_slot)

        normalized: dict[str, Any] = {}
        if display_name not in (None, ""):
            normalized["display_name"] = str(display_name)
        if entry_key not in (None, ""):
            normalized["entry_key"] = str(entry_key)
        if vip_entry_key not in (None, ""):
            normalized["vip_entry_key"] = str(vip_entry_key)

        for key in ("rank", "pts", "pmr"):
            value = row.get(key)
            if value not in (None, ""):
                normalized[key] = value

        if players_live:
            normalized["players_live"] = players_live

        if normalized:
            normalized_rows.append(normalized)

    return normalized_rows


def _build_unique_name_to_player_key_from_vip_lineups(vip_lineups: list[dict[str, Any]]) -> dict[str, str]:
    keys_by_name: dict[str, set[str]] = {}

    for vip_row in vip_lineups:
        if not isinstance(vip_row, dict):
            continue
        slots = vip_row.get("players_live")
        if not isinstance(slots, list):
            continue
        for slot in slots:
            if not isinstance(slot, dict):
                continue
            player_name = slot.get("player_name") or slot.get("name")
            player_key = slot.get("player_key")
            if player_name in (None, "") or player_key in (None, ""):
                continue
            keys_by_name.setdefault(normalize_name(player_name), set()).add(str(player_key))

    unique_name_to_key: dict[str, str] = {}
    for name_key, keys in keys_by_name.items():
        if len(keys) == 1:
            unique_name_to_key[name_key] = next(iter(keys))

    return unique_name_to_key


def _merge_unique_name_to_player_keys(
    primary: dict[str, str],
    secondary: dict[str, str],
) -> dict[str, str]:
    merged = dict(primary)
    for name_key, key in secondary.items():
        existing = merged.get(name_key)
        if existing is None:
            merged[name_key] = key
            continue
        if existing != key:
            merged.pop(name_key, None)
    return merged


def _normalize_top_remaining_players(
    rows: list[Any],
    unique_name_to_player_key: dict[str, str],
) -> list[dict[str, Any]]:
    normalized_rows: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        mapped = dict(row)
        player_name = mapped.get("player_name")
        player_key = mapped.get("player_key")
        if player_key in (None, "") and player_name not in (None, ""):
            player_key = unique_name_to_player_key.get(normalize_name(player_name))
        if player_key not in (None, ""):
            mapped["player_key"] = str(player_key)
        normalized_rows.append(mapped)
    return normalized_rows


def _collect_source_snapshot(
    *,
    sport: str,
    contest_id: int | None = None,
    standings_limit: int = DEFAULT_STANDINGS_LIMIT,
) -> dict[str, Any]:
    sport_map = _sport_choices()
    sport_cls = sport_map[sport.upper()]
    contest_db: ContestDatabase | None = None
    try:
        contest_db = ContestDatabase(str(state.contests_db_path()))
    except Exception:
        contest_db = None

    try:
        candidate_rows: list[tuple] = []
        if contest_db is not None:
            candidate_rows = contest_db.get_live_contest_candidates(
                sport_cls.name,
                entry_fee=sport_cls.sheet_min_entry_fee,
                keyword=sport_cls.keyword,
                limit=CANDIDATE_LIMIT,
            )

        mode = "primary_live"
        selected: tuple | None = None
        dk = Draftkings()
        if contest_id is not None:
            mode = "explicit_id"
            if contest_db is not None:
                selected = contest_db.get_contest_by_id(int(contest_id))
            if not selected:
                selected = _contest_row_from_detail(int(contest_id), dk.get_contest_detail(int(contest_id)))
        else:
            if contest_db is None:
                raise RuntimeError("Contest DB unavailable for primary live selection")
            live = contest_db.get_live_contest(sport_cls.name, sport_cls.sheet_min_entry_fee, sport_cls.keyword)
            if live:
                selected = contest_db.get_contest_by_id(int(live[0]))

        if not selected:
            raise RuntimeError(f"No contest found for sport={sport_cls.name}")

        dk_id, contest_name, draft_group, positions_paid, start_date, entry_fee, entries = selected[:7]
        contest_state = None
        contest_completed = None
        prize_pool = None
        max_entries = entries
        max_entries_per_user = None
        if len(selected) >= 8:
            contest_state = selected[7]
        if len(selected) >= 9:
            contest_completed = selected[8]
        if len(selected) >= 10 and selected[9] not in (None, ""):
            prize_pool = selected[9]
        if len(selected) >= 11 and selected[10] not in (None, ""):
            max_entries_per_user = selected[10]
        if contest_db is not None:
            state_row = contest_db.get_contest_state(int(dk_id))
            if state_row:
                contest_state, contest_completed = state_row
            contract_metadata = contest_db.get_contest_contract_metadata(int(dk_id))
            if contract_metadata:
                prize_pool, contest_capacity, per_user_limit, _db_entry_count = contract_metadata
                if contest_capacity not in (None, ""):
                    max_entries = contest_capacity
                if per_user_limit not in (None, ""):
                    max_entries_per_user = per_user_limit
        logger.info("selected contest id=%s mode=%s", dk_id, mode)

        now_et = datetime.datetime.now(ZoneInfo("America/New_York"))
        salary_path = os.path.join(SALARY_DIR, f"DKSalaries_{sport_cls.name}_{now_et:%A}.csv")
        if draft_group:
            dk.download_salary_csv(sport_cls.name, draft_group, salary_path)

        standings_rows = dk.download_contest_rows(
            int(dk_id),
            timeout=30,
            cookies_dump_file=COOKIES_FILE,
            contest_dir=CONTEST_DIR,
        )
        if not standings_rows:
            raise RuntimeError(f"Contest standings unavailable for contest_id={dk_id}")
        leaderboard_payout_by_entry: dict[str, int] = {}
        try:
            leaderboard_payload = dk.get_leaderboard(int(dk_id))
            if isinstance(leaderboard_payload, dict):
                leaderboard_payout_by_entry = _leaderboard_payout_map(leaderboard_payload)
        except Exception:
            logger.warning("leaderboard payout lookup failed for contest_id=%s", dk_id, exc_info=True)

        vips = load_vips()
        results = Results(
            sport_cls,
            int(dk_id),
            salary_path,
            positions_paid,
            standings_rows=standings_rows,
            vips=vips,
        )
        results.name = contest_name
        results.positions_paid = positions_paid

        vip_entries: dict[str, dict[str, Any] | str] = {}
        for vip in results.vip_list:
            if not vip.name or not vip.player_id:
                continue
            vip_entries[vip.name] = {
                "entry_key": vip.player_id,
                "pmr": vip.pmr,
                "rank": vip.rank,
                "pts": vip.pts,
            }

        player_salary_map = {name: player.salary for name, player in results.players.items()}
        vip_lineups = (
            dk.get_vip_lineups(
                int(dk_id),
                int(draft_group),
                vips,
                vip_entries=vip_entries,
                player_salary_map=player_salary_map,
            )
            if draft_group
            else []
        )

        vip_lookup = {vip.name for vip in results.vip_list}
        standings = []
        cash_points_cutoff = results.min_cash_pts if results.min_rank > 0 else None
        for user in results.users:
            parsed_rank = _rank_numeric(user.rank)
            points = to_float(user.pts)
            entry_key = user.player_id
            payout_cents = leaderboard_payout_by_entry.get(str(entry_key), None) if entry_key else None
            if isinstance(payout_cents, int):
                is_cashing = payout_cents > 0
            elif isinstance(points, (int, float)) and isinstance(cash_points_cutoff, (int, float)):
                is_cashing = float(points) >= float(cash_points_cutoff)
            else:
                is_cashing = False
            standings.append(
                {
                    "rank": parsed_rank if parsed_rank is not None else user.rank,
                    "entry_key": entry_key,
                    "username": user.name,
                    "pmr": to_float(user.pmr),
                    "points": points,
                    "payout_cents": payout_cents,
                    "is_cashing": is_cashing,
                    "ownership_remaining_total_pct": _ownership_remaining_for_user(user),
                    "is_vip": user.name in vip_lookup,
                }
            )

        players = []
        for player in results.players.values():
            players.append(
                {
                    "name": player.name,
                    "position": player.pos,
                    "roster_positions": list(player.roster_pos),
                    "salary": player.salary,
                    "team": player.team_abbv,
                    "game_status": player.game_info,
                    "matchup": player.matchup_info,
                    "ownership_pct": float(player.ownership) * 100,
                    "fantasy_points": player.fpts,
                    "value": player.value,
                }
            )
        players.sort(
            key=lambda item: (
                item["position"] or "",
                item["name"] or "",
                int(item["salary"] or 0),
            )
        )

        standings.sort(
            key=lambda item: (
                item["rank"] is None,
                _rank_numeric(item["rank"]) if _rank_numeric(item["rank"]) is not None else 10**9,
                str(item["rank"] if item["rank"] is not None else ""),
                item["username"] or "",
                str(item["entry_key"] or ""),
            )
        )

        full_standings = list(standings)

        ownership_values = [
            row["ownership_remaining_total_pct"]
            for row in full_standings
            if row["ownership_remaining_total_pct"] is not None
        ]
        ownership_remaining_total = sum(ownership_values) / len(ownership_values) if ownership_values else None
        avg_salary_per_player_remaining = _avg_salary_per_player_remaining(results.users)

        top_remaining_players: list[dict[str, Any]] = []
        if results.non_cashing_users > 0:
            for name, count in results.non_cashing_players.items():
                top_remaining_players.append(
                    {
                        "player_name": name,
                        "ownership_remaining_pct": (float(count) / results.non_cashing_users) * 100,
                    }
                )
        top_remaining_players.sort(key=lambda item: (-item["ownership_remaining_pct"], item["player_name"]))
        top_remaining_players = top_remaining_players[:10]

        watchlist_entries: list[dict[str, Any]] = []
        for row in sorted(
            full_standings,
            key=lambda item: (
                -(float(item["ownership_remaining_total_pct"]))
                if isinstance(item.get("ownership_remaining_total_pct"), (int, float))
                else float("-inf"),
                _rank_numeric(item.get("rank")) if _rank_numeric(item.get("rank")) is not None else 10**9,
                str(item.get("username") or ""),
            ),
        ):
            ownership_remaining_pct = row.get("ownership_remaining_total_pct")
            if not isinstance(ownership_remaining_pct, (int, float)):
                continue
            watchlist_entries.append(
                {
                    "entry_key": row.get("entry_key"),
                    "display_name": row.get("username"),
                    "ownership_remaining_pct": ownership_remaining_pct,
                    "current_rank": _rank_numeric(row.get("rank")),
                    "current_points": to_float(row.get("points")),
                    "pmr": to_float(row.get("pmr")),
                }
            )
        watchlist_entries = watchlist_entries[:10]

        total_before = len(full_standings)
        limit = standings_limit if standings_limit and standings_limit > 0 else None
        applied = bool(limit and total_before > limit)
        if applied and limit is not None:
            standings = full_standings[:limit]
        else:
            standings = full_standings

        cash_rank = results.min_rank if results.min_rank > 0 else None
        cash_points = results.min_cash_pts if cash_rank is not None else None
        cash_delta = None
        if cash_rank is not None:
            below_cash = [
                row
                for row in full_standings
                if (rank_num := _rank_numeric(row["rank"])) is not None and rank_num > int(cash_rank)
            ]
            if below_cash and cash_points is not None:
                first_below = below_cash[0]
                if first_below["points"] is not None:
                    cash_delta = float(first_below["points"]) - float(cash_points)

        trains = TrainFinder(results.users).get_users_above_salary_spent(SALARY_LIMIT)
        train_clusters = []
        for key, cluster in trains.items():
            if cluster.get("count", 0) <= 1:
                continue
            members = [user for user in results.users if f"{user.pts}-{user.pmr}" == key]
            members.sort(
                key=lambda user: (
                    user.rank is None,
                    _rank_numeric(user.rank) if _rank_numeric(user.rank) is not None else 10**9,
                    str(user.rank if user.rank is not None else ""),
                    str(user.player_id),
                )
            )
            signature = _lineup_signature(members[0]) if members else ""
            train_clusters.append(
                {
                    "cluster_id": _cluster_id_from_signature(signature),
                    "cluster_rule": "salary_remaining<=40000_and_same_points_pmr",
                    "user_count": int(cluster.get("count") or 0),
                    "rank": cluster.get("rank"),
                    "points": to_float(cluster.get("pts")),
                    "pmr": to_float(cluster.get("pmr")),
                    "lineup_signature": signature,
                    "entry_keys": [member.player_id for member in members],
                }
            )
        train_clusters.sort(
            key=lambda item: (
                -item["user_count"],
                -(item["points"] if item["points"] is not None else -(10**9)),
                item["lineup_signature"],
            )
        )

        return {
            "sport": sport_cls.name,
            "contest": {
                "contest_id": dk_id,
                "name": contest_name,
                "sport": sport_cls.name.lower(),
                "draft_group": draft_group,
                "start_time_utc": to_utc_iso(start_date),
                "is_primary": True,
                "contest_type": "classic",
                "state": _normalize_contest_state(contest_state, contest_completed),
                "entry_fee": entry_fee,
                "currency": "USD",
                "entries": max_entries,
                "max_entries": max_entries,
                "max_entries_per_user": max_entries_per_user,
                "prize_pool": prize_pool,
                "positions_paid": positions_paid,
            },
            "selection": {
                "selected_contest_id": dk_id,
                "reason": _build_selection_reason(
                    mode=mode,
                    sport=sport_cls.name,
                    min_entry_fee=sport_cls.sheet_min_entry_fee,
                    keyword=sport_cls.keyword,
                    selected_from_candidate_count=len(candidate_rows),
                    contest_id=int(dk_id) if mode == "explicit_id" else None,
                ),
            },
            "candidates": _summarize_candidates(candidate_rows, top_n=CANDIDATE_LIMIT),
            "cash_line": {
                "cutoff_type": "positions_paid",
                "rank": cash_rank,
                "points": cash_points,
                "delta_to_cash": cash_delta,
            },
            "vip_lineups": vip_lineups,
            "players": players,
            "ownership": {
                "ownership_remaining_total_pct": ownership_remaining_total,
                "avg_salary_per_player_remaining": avg_salary_per_player_remaining,
                "non_cashing_user_count": results.non_cashing_users,
                "non_cashing_avg_pmr": results.non_cashing_avg_pmr,
                "watchlist_entries": watchlist_entries,
                "non_cashing_top_remaining_players": top_remaining_players,
                "top_remaining_players": top_remaining_players,
            },
            "train_clusters": train_clusters,
            "standings": standings,
            "truncation": {
                "applied": applied,
                "limit": limit,
                "total_rows_before_truncation": total_before,
                "total_rows_after_truncation": len(standings),
            },
        }
    finally:
        if contest_db is not None:
            contest_db.close()


def collect_raw_bundle(
    *,
    sport: str,
    contest_id: int | None = None,
    standings_limit: int = DEFAULT_STANDINGS_LIMIT,
) -> dict[str, Any]:
    raw = _collect_source_snapshot(
        sport=sport,
        contest_id=contest_id,
        standings_limit=standings_limit,
    )

    standings = list(raw.get("standings") or [])
    players, unique_name_to_player_key = _normalize_players(
        list(raw.get("players") or []),
        str(raw.get("sport") or sport),
    )
    vip_lineups = _normalize_vip_lineup_rows(
        list(raw.get("vip_lineups") or []),
        standings,
        str(raw.get("sport") or sport),
        unique_name_to_player_key,
    )
    unique_name_to_player_key = _merge_unique_name_to_player_keys(
        unique_name_to_player_key,
        _build_unique_name_to_player_key_from_vip_lineups(vip_lineups),
    )
    train_clusters = [cluster for cluster in list(raw.get("train_clusters") or []) if isinstance(cluster, dict)]
    ownership = dict(raw.get("ownership") or {})
    for field in ("non_cashing_top_remaining_players", "top_remaining_players"):
        rows = ownership.get(field)
        if isinstance(rows, list):
            ownership[field] = _normalize_top_remaining_players(rows, unique_name_to_player_key)

    selection = dict(raw.get("selection") or {})
    return {
        "sport": raw.get("sport"),
        "contest": dict(raw.get("contest") or {}),
        "selected_contest_id": selection.get("selected_contest_id"),
        "selection_reason": selection.get("reason"),
        "candidates": list(raw.get("candidates") or []),
        "cash_line": dict(raw.get("cash_line") or {}),
        "players": players,
        "ownership": ownership,
        "standings": standings,
        "vip_lineups": vip_lineups,
        "train_clusters": train_clusters,
        "truncation": dict(raw.get("truncation") or {}),
        "metadata": dict(raw.get("metadata") or {}),
    }
