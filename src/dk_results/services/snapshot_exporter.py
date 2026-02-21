import copy
import datetime
import hashlib
import json
import logging
import os
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any
from zoneinfo import ZoneInfo

import yaml
from dfs_common import state

from dk_results.classes.contestdatabase import ContestDatabase
from dk_results.classes.draftkings import Draftkings
from dk_results.classes.results import Results
from dk_results.classes.sport import Sport
from dk_results.classes.trainfinder import TrainFinder
from dk_results.config import load_settings
from dk_results.paths import repo_file

logger = logging.getLogger(__name__)

CONTEST_DIR = str(repo_file("contests"))
SALARY_DIR = str(repo_file("salary"))
SALARY_LIMIT = 40000
COOKIES_FILE = str(repo_file("pickled_cookies_works.txt"))
CANDIDATE_LIMIT = 5
DEFAULT_STANDINGS_LIMIT = 500

ID_FIELDS = {
    "contest_id",
    "draft_group",
    "selected_contest_id",
    "entry_key",
    "vip_entry_key",
    "cluster_id",
}

CANONICAL_DISALLOWED_KEYS = {"username", "player_id", "playerId", "dk_player_id"}

SOURCE_ENDPOINTS = [
    "contests_db.get_live_contest",
    "contests_db.get_live_contest_candidates",
    "draftkings.download_salary_csv",
    "draftkings.download_contest_rows",
    "draftkings.get_vip_lineups",
]

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover

    def load_dotenv(*_args, **_kwargs):
        return False


def load_vips() -> list[str]:
    vip_path = repo_file("vips.yaml")
    try:
        with open(vip_path, "r") as f:
            vips = yaml.safe_load(f) or []
        if not isinstance(vips, list):
            return []
        return [str(x).strip() for x in vips if str(x).strip()]
    except Exception:
        return []


def configure_runtime() -> None:
    load_dotenv()
    settings = load_settings()
    if settings.dfs_state_dir and not os.getenv("DFS_STATE_DIR"):
        os.environ["DFS_STATE_DIR"] = settings.dfs_state_dir
    if settings.spreadsheet_id and not os.getenv("SPREADSHEET_ID"):
        os.environ["SPREADSHEET_ID"] = settings.spreadsheet_id


def _sport_choices() -> dict[str, type[Sport]]:
    return {sport.name.upper(): sport for sport in Sport.__subclasses__()}


def normalize_sport_name(raw: str) -> str:
    value = (raw or "").strip().upper()
    choices = _sport_choices()
    if value not in choices:
        raise ValueError(f"Unsupported sport: {raw}")
    return choices[value].name


def to_utc_iso(value: datetime.datetime | str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        text = text.replace("Z", "+00:00")
        try:
            parsed = datetime.datetime.fromisoformat(text)
        except ValueError:
            return None
        value = parsed

    if value.tzinfo is None:
        value = value.replace(tzinfo=ZoneInfo("America/New_York"))
    value = value.astimezone(datetime.timezone.utc)
    return value.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _to_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


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


def _to_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _to_int_flexible(value: Any) -> int | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip()
    if not text:
        return None
    text = text.replace("$", "").replace(",", "")
    try:
        return int(float(text))
    except ValueError:
        return None


def _to_percent(value: Any) -> float | None:
    if value in (None, ""):
        return None
    numeric: float | None
    if isinstance(value, (int, float)):
        numeric = float(value)
    else:
        text = str(value).strip()
        if not text:
            return None
        if text.endswith("%"):
            text = text[:-1].strip()
        numeric = _to_float(text)
    if numeric is None:
        return None
    if 0 <= numeric <= 1:
        return numeric * 100
    return numeric


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


def _lineup_signature(user: Any) -> str:
    lineup_obj = getattr(user, "lineupobj", None)
    if not lineup_obj:
        return ""
    names = [getattr(player, "name", "").strip() for player in lineup_obj.lineup]
    return "|".join(names)


def cluster_id_from_signature(signature: str) -> str:
    return hashlib.sha1(signature.encode("utf-8")).hexdigest()[:12]


def build_selection_reason(
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


def summarize_candidates(rows: list[tuple], top_n: int = CANDIDATE_LIMIT) -> list[dict[str, Any]]:
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


def _default_snapshot(sport: str) -> dict[str, Any]:
    return {
        "snapshot_version": "v1",
        "snapshot_generated_at_utc": None,
        "sport": sport,
        "contest": {
            "contest_id": None,
            "name": None,
            "draft_group": None,
            "start_time_utc": None,
            "is_primary": True,
            "entry_fee": None,
            "entries": None,
            "positions_paid": None,
        },
        "selection": {
            "selected_contest_id": None,
            "reason": {
                "mode": None,
                "criteria": {},
                "tie_breakers": [],
                "selected_from_candidate_count": 0,
            },
        },
        "candidates": [],
        "cash_line": {
            "cutoff_type": "positions_paid",
            "rank": None,
            "points": None,
            "delta_to_cash": None,
        },
        "vip_lineups": [],
        "players": [],
        "ownership": {
            "ownership_remaining_total_pct": None,
            "non_cashing_user_count": 0,
            "non_cashing_avg_pmr": 0.0,
            "top_remaining_players": [],
        },
        "train_clusters": [],
        "standings": [],
        "truncation": {
            "applied": False,
            "limit": None,
            "total_rows_before_truncation": 0,
            "total_rows_after_truncation": 0,
        },
        "metadata": {
            "missing_fields": [],
            "warnings": [],
            "source_endpoints": SOURCE_ENDPOINTS[:],
        },
    }


def _merge_dict(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge_dict(result[key], value)
        else:
            result[key] = value
    return result


def _find_missing_fields(value: Any, path: str = "") -> list[str]:
    missing: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else key
            missing.extend(_find_missing_fields(child, child_path))
        return missing
    if isinstance(value, list):
        for idx, child in enumerate(value):
            child_path = f"{path}.{idx}" if path else str(idx)
            missing.extend(_find_missing_fields(child, child_path))
        return missing
    if value is None:
        return [path]
    return []


def _contest_row_from_detail(dk_id: int, detail: dict[str, Any]) -> tuple:
    contest_detail = detail.get("contestDetail", {})
    payout_summary = contest_detail.get("payoutSummary") or []
    positions_paid = None
    if payout_summary:
        positions_paid = payout_summary[0].get("maxPosition")
    start_time = contest_detail.get("contestStartTime")
    prize_pool = (
        contest_detail.get("totalPrizePool")
        or contest_detail.get("totalPrizes")
        or contest_detail.get("totalPayouts")
        or contest_detail.get("totalPayout")
        or contest_detail.get("prizePool")
        or contest_detail.get("payout")
    )
    max_entries_per_user = (
        contest_detail.get("maxEntriesPerUser")
        or contest_detail.get("maximumEntriesPerUser")
        or contest_detail.get("maxEntriesPerPerson")
        or contest_detail.get("maxEntryCount")
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


def collect_snapshot_data(
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
            points = _to_float(user.pts)
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
                    "pmr": _to_float(user.pmr),
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

        total_before = len(standings)
        limit = standings_limit if standings_limit and standings_limit > 0 else None
        applied = bool(limit and total_before > limit)
        if applied and limit is not None:
            standings = standings[:limit]

        ownership_values = [
            row["ownership_remaining_total_pct"]
            for row in standings
            if row["ownership_remaining_total_pct"] is not None
        ]
        ownership_remaining_total = sum(ownership_values) / len(ownership_values) if ownership_values else None

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

        cash_rank = results.min_rank if results.min_rank > 0 else None
        cash_points = results.min_cash_pts if cash_rank is not None else None
        cash_delta = None
        if cash_rank is not None:
            below_cash = [
                row
                for row in standings
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
            members = [u for u in results.users if f"{u.pts}-{u.pmr}" == key]
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
                    "cluster_id": cluster_id_from_signature(signature),
                    "cluster_rule": "salary_remaining<=40000_and_same_points_pmr",
                    "user_count": int(cluster.get("count") or 0),
                    "rank": cluster.get("rank"),
                    "points": _to_float(cluster.get("pts")),
                    "pmr": _to_float(cluster.get("pmr")),
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
                "reason": build_selection_reason(
                    mode=mode,
                    sport=sport_cls.name,
                    min_entry_fee=sport_cls.sheet_min_entry_fee,
                    keyword=sport_cls.keyword,
                    selected_from_candidate_count=len(candidate_rows),
                    contest_id=int(dk_id) if mode == "explicit_id" else None,
                ),
            },
            "candidates": summarize_candidates(candidate_rows, top_n=CANDIDATE_LIMIT),
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
                "non_cashing_user_count": results.non_cashing_users,
                "non_cashing_avg_pmr": results.non_cashing_avg_pmr,
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


def build_snapshot(
    *, sport: str, contest_id: int | None = None, standings_limit: int = DEFAULT_STANDINGS_LIMIT
) -> dict[str, Any]:
    collected = collect_snapshot_data(
        sport=sport,
        contest_id=contest_id,
        standings_limit=standings_limit,
    )
    snapshot = _merge_dict(_default_snapshot(sport), collected)
    snapshot["snapshot_generated_at_utc"] = to_utc_iso(datetime.datetime.now(datetime.timezone.utc))

    missing = [path for path in _find_missing_fields(snapshot) if not path.startswith("metadata.missing_fields")]
    snapshot["metadata"]["missing_fields"] = sorted(set(missing))
    return snapshot


def _round_for_key(key: str, value: float) -> float:
    if key.endswith("_pct"):
        return round(value, 4)
    if key in {"points", "delta_to_cash", "pmr", "pts", "fantasy_points", "value"}:
        return round(value, 2)
    return value


def _normalize_value(value: Any, path: str, warnings: list[dict[str, Any]]) -> Any:
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else key
            normalized = _normalize_value(child, child_path, warnings)
            if key in ID_FIELDS and normalized is not None:
                normalized = str(normalized)
            if key == "entry_keys" and isinstance(normalized, list):
                normalized = [str(item) for item in normalized]
            if key == "ownership_remaining_total_pct" and isinstance(normalized, (int, float)):
                normalized = round(float(normalized), 4)
            elif isinstance(normalized, float):
                normalized = _round_for_key(key, normalized)
            out[key] = normalized
        return out

    if isinstance(value, list):
        return [
            _normalize_value(item, f"{path}.{idx}" if path else str(idx), warnings) for idx, item in enumerate(value)
        ]

    return value


def normalize_snapshot_for_output(snapshot: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(snapshot)
    warnings: list[dict[str, Any]] = list(result.get("metadata", {}).get("warnings", []))
    normalized = _normalize_value(result, "", warnings)
    if "metadata" not in normalized:
        normalized["metadata"] = {}
    normalized["metadata"]["warnings"] = warnings
    return normalized


def snapshot_to_json(snapshot: dict[str, Any]) -> str:
    normalized = normalize_snapshot_for_output(snapshot)
    return to_stable_json(normalized)


def to_stable_json(payload: Any) -> str:
    return (
        json.dumps(
            payload,
            sort_keys=True,
            indent=2,
            separators=(",", ":"),
            ensure_ascii=True,
        )
        + "\n"
    )


def _cash_line_contract(cash_line: dict[str, Any]) -> dict[str, Any]:
    raw = str(cash_line.get("cutoff_type") or "").strip().lower()
    if raw in {"positions_paid", "rank"}:
        cutoff_type = "rank"
    elif raw == "points":
        cutoff_type = "points"
    else:
        cutoff_type = "unknown"
    return {
        "cutoff_type": cutoff_type,
        "rank_cutoff": cash_line.get("rank"),
        "points_cutoff": cash_line.get("points"),
    }


def _ownership_watchlist_contract(ownership: dict[str, Any], updated_at: str) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    for row in ownership.get("top_remaining_players") or []:
        if not isinstance(row, dict):
            continue
        entry_key = row.get("entry_key")
        display_name = row.get("display_name") or row.get("player_name")
        if display_name in (None, "") and entry_key not in (None, ""):
            display_name = str(entry_key)
        entries.append(
            {
                "display_name": display_name,
                "ownership_remaining_pct": _to_float(row.get("ownership_remaining_pct")),
                "entry_key": entry_key,
                "current_rank": _rank_numeric(row.get("current_rank")),
                "current_points": _to_float(row.get("current_points")),
                "pmr": _to_float(row.get("pmr")),
            }
        )
    top_n_default_raw = ownership.get("top_n_default")
    if isinstance(top_n_default_raw, (int, float)):
        top_n_default = int(top_n_default_raw)
    else:
        top_n_default = 10
    if top_n_default <= 0:
        top_n_default = 10
    return {
        "updated_at": updated_at,
        "ownership_remaining_total_pct": _to_float(ownership.get("ownership_remaining_total_pct")),
        "top_n_default": top_n_default,
        "entries": entries,
    }


def _normalize_standings_rows(rows: list[Any]) -> list[dict[str, Any]]:
    normalized_rows: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        entry_key = row.get("entry_key")
        display_name = row.get("display_name") or row.get("username")
        if display_name in (None, "") and entry_key not in (None, ""):
            display_name = str(entry_key)
        payout_cents = _to_int(row.get("payout_cents"))
        normalized_rows.append(
            {
                "entry_key": entry_key,
                "display_name": display_name,
                "rank": _rank_numeric(row.get("rank")),
                "points": _to_float(row.get("points")),
                "pmr": _to_float(row.get("pmr")),
                "ownership_remaining_pct": _to_float(
                    row.get("ownership_remaining_total_pct")
                    if row.get("ownership_remaining_total_pct") is not None
                    else row.get("ownership_remaining_pct")
                ),
                "payout_cents": payout_cents,
                "is_cashing": bool(row.get("is_cashing"))
                if isinstance(row.get("is_cashing"), bool)
                else isinstance(payout_cents, int) and payout_cents > 0,
                "is_vip": bool(row.get("is_vip")),
            }
        )
    return normalized_rows


def _unique_standings_by_display_name(
    rows: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    counts: dict[str, int] = {}
    for row in rows:
        display_name = row.get("display_name")
        if display_name in (None, ""):
            continue
        key = str(display_name)
        counts[key] = counts.get(key, 0) + 1
    unique: dict[str, dict[str, Any]] = {}
    for row in rows:
        display_name = row.get("display_name")
        if display_name in (None, ""):
            continue
        key = str(display_name)
        if counts.get(key) == 1:
            unique[key] = row
    return unique


def _build_player_name_lookup(players: list[Any]) -> dict[str, str]:
    lookup: dict[str, str] = {}
    collisions: set[str] = set()
    for player in players:
        if not isinstance(player, dict):
            continue
        name = str(player.get("name") or "").strip()
        if not name:
            continue
        key = name.lower()
        if key in lookup and lookup[key] != name:
            collisions.add(key)
        else:
            lookup[key] = name
    for key in collisions:
        lookup.pop(key, None)
    return lookup


def _canonical_player_name(raw_name: Any, lookup: dict[str, str]) -> str | None:
    name = str(raw_name or "").strip()
    if not name:
        return None
    if name.lower() in lookup:
        return lookup[name.lower()]
    return None


def _canonical_or_raw_player_name(raw_name: Any, lookup: dict[str, str]) -> str | None:
    name = str(raw_name or "").strip()
    if not name:
        return None
    canonical = _canonical_player_name(name, lookup)
    return canonical if canonical is not None else name


def _cluster_composition(cluster: dict[str, Any], player_lookup: dict[str, str]) -> list[dict[str, Any]]:
    signature = str(cluster.get("lineup_signature") or "").strip()
    if not signature:
        return []
    names = [part.strip() for part in signature.split("|") if part.strip()]
    composition: list[dict[str, Any]] = []
    for index, name in enumerate(names):
        canonical_name = _canonical_player_name(name, player_lookup)
        if canonical_name is None:
            continue
        composition.append({"slot": f"SLOT_{index + 1}", "player_name": canonical_name})
    return composition


def _train_clusters_contract(
    clusters: list[Any],
    updated_at: str,
    player_lookup: dict[str, str],
    standings_by_entry_key: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    mapped_clusters: list[dict[str, Any]] = []
    max_shared = 0
    for row in clusters:
        if not isinstance(row, dict):
            continue
        composition = _cluster_composition(row, player_lookup)
        max_shared = max(max_shared, len(composition))

        entry_keys = [str(v) for v in (row.get("entry_keys") or []) if str(v)]
        sample_entries: list[dict[str, Any]] = []
        for entry_key in entry_keys:
            standing_row = standings_by_entry_key.get(entry_key, {})
            display_name = standing_row.get("display_name")
            if display_name in (None, "") and entry_key:
                display_name = str(entry_key)
            sample_entries.append(
                {
                    "entry_key": entry_key,
                    "display_name": display_name,
                    "rank": _rank_numeric(standing_row.get("rank")),
                    "points": _to_float(standing_row.get("points")),
                    "pmr": _to_float(standing_row.get("pmr")),
                }
            )

        pmr_values = [item.get("pmr") for item in sample_entries if isinstance(item.get("pmr"), (int, float))]
        ownership_values = [
            standings_by_entry_key.get(key, {}).get("ownership_remaining_pct")
            for key in entry_keys
            if isinstance(standings_by_entry_key.get(key, {}).get("ownership_remaining_pct"), (int, float))
        ]

        mapped = {
            "cluster_key": row.get("cluster_id") or row.get("lineup_signature"),
            "entry_count": int(row.get("user_count") or len(entry_keys)),
            "best_rank": _rank_numeric(row.get("rank")),
            "best_points": _to_float(row.get("points")),
            "avg_pmr": (sum(pmr_values) / len(pmr_values)) if pmr_values else _to_float(row.get("pmr")),
            "avg_ownership_remaining_pct": (sum(ownership_values) / len(ownership_values))
            if ownership_values
            else None,
            "composition": composition,
            "sample_entries": sample_entries,
        }
        mapped_clusters.append(mapped)
    return {
        "updated_at": updated_at,
        "cluster_rule": {
            "type": "shared_slots",
            "min_shared": max_shared if max_shared > 0 else 0,
        },
        "clusters": mapped_clusters,
    }


def _vip_slots_from_lineup(lineup: Any, player_lookup: dict[str, str]) -> list[dict[str, Any]]:
    if not isinstance(lineup, list):
        return []
    slots: list[dict[str, Any]] = []
    for index, item in enumerate(lineup):
        if isinstance(item, dict):
            player_name = item.get("player_name") or item.get("name")
            slot = item.get("slot") or item.get("position") or item.get("pos") or f"SLOT_{index + 1}"
            multiplier = item.get("multiplier")
        else:
            player_name = str(item)
            slot = f"SLOT_{index + 1}"
            multiplier = None
        canonical_name = _canonical_player_name(player_name, player_lookup)
        if canonical_name is None:
            continue
        slot_row: dict[str, Any] = {"slot": slot, "player_name": canonical_name}
        if multiplier is not None:
            slot_row["multiplier"] = multiplier
        slots.append(slot_row)
    return slots


def _build_player_status_lookup(players: list[Any]) -> dict[str, str]:
    lookup: dict[str, str] = {}
    for player in players:
        if not isinstance(player, dict):
            continue
        name = str(player.get("name") or "").strip()
        status = str(player.get("game_status") or "").strip()
        if not name or not status:
            continue
        lookup[name.lower()] = status
    return lookup


def _vip_players_live_from_lineup(
    lineup: Any,
    player_lookup: dict[str, str],
    player_status_lookup: dict[str, str],
) -> list[dict[str, Any]]:
    if not isinstance(lineup, list):
        return []

    rows: list[dict[str, Any]] = []
    for index, item in enumerate(lineup):
        if isinstance(item, dict):
            raw_name = item.get("player_name") or item.get("name")
            slot = item.get("slot") or item.get("position") or item.get("pos") or f"SLOT_{index + 1}"
            ownership_pct = _to_percent(
                item.get("ownership_pct") if item.get("ownership_pct") is not None else item.get("ownership")
            )
            salary = _to_int_flexible(item.get("salary"))
            points = _to_float(item.get("points") if item.get("points") is not None else item.get("pts"))
            value = _to_float(item.get("value"))
            rt_projection = _to_float(
                item.get("rt_projection") if item.get("rt_projection") is not None else item.get("rtProj")
            )
            time_remaining_display_raw = (
                item.get("time_remaining_display")
                if item.get("time_remaining_display") is not None
                else item.get("timeStatus")
            )
            time_remaining_minutes = _to_float(
                item.get("time_remaining_minutes")
                if item.get("time_remaining_minutes") is not None
                else time_remaining_display_raw
            )
            stats_text_raw = item.get("stats_text") if item.get("stats_text") is not None else item.get("stats")
            game_status = item.get("game_status")
        else:
            raw_name = item
            slot = f"SLOT_{index + 1}"
            ownership_pct = None
            salary = None
            points = None
            value = None
            rt_projection = None
            time_remaining_display_raw = None
            time_remaining_minutes = None
            stats_text_raw = None
            game_status = None

        player_name = _canonical_or_raw_player_name(raw_name, player_lookup)
        if player_name is None:
            continue

        status_text = str(game_status).strip() if game_status not in (None, "") else ""
        if not status_text:
            status_text = player_status_lookup.get(player_name.lower(), "")

        time_remaining_display = (
            str(time_remaining_display_raw).strip() if time_remaining_display_raw not in (None, "") else ""
        )
        stats_text = str(stats_text_raw).strip() if stats_text_raw not in (None, "") else ""

        live_row: dict[str, Any] = {
            "slot": str(slot),
            "player_name": player_name,
        }
        if status_text:
            live_row["game_status"] = status_text
        if isinstance(ownership_pct, (int, float)):
            live_row["ownership_pct"] = float(ownership_pct)
        if salary is not None:
            live_row["salary"] = salary
        if isinstance(points, (int, float)):
            live_row["points"] = float(points)
        if isinstance(value, (int, float)):
            live_row["value"] = float(value)
        if isinstance(rt_projection, (int, float)):
            live_row["rt_projection"] = float(rt_projection)
        if time_remaining_display:
            live_row["time_remaining_display"] = time_remaining_display
        if isinstance(time_remaining_minutes, (int, float)):
            live_row["time_remaining_minutes"] = float(time_remaining_minutes)
        if stats_text:
            live_row["stats_text"] = stats_text
        rows.append(live_row)

    return rows


def _vip_lineups_contract(
    vip_lineups: list[Any],
    player_lookup: dict[str, str],
    player_status_lookup: dict[str, str],
    updated_at: str,
    standings_by_entry_key: dict[str, dict[str, Any]],
    standings_by_username: dict[str, dict[str, Any]],
    cash_line: dict[str, Any],
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for row in vip_lineups:
        if not isinstance(row, dict):
            continue
        display_name = row.get("display_name") or row.get("username") or row.get("user")
        entry_key = row.get("entry_key")
        standings_row = standings_by_entry_key.get(str(entry_key), {})
        if not standings_row and display_name:
            standings_row = standings_by_username.get(str(display_name), {})
        if entry_key in (None, "") and standings_row:
            entry_key = standings_row.get("entry_key")
        if display_name in (None, "") and entry_key not in (None, ""):
            display_name = str(entry_key)
        current_points = row.get("pts") if row.get("pts") is not None else standings_row.get("points")
        current_rank = row.get("rank") if row.get("rank") is not None else standings_row.get("rank")
        current_points_num = _to_float(current_points)
        current_rank_num = _rank_numeric(current_rank)
        points_cutoff = cash_line.get("points_cutoff")
        cash_line_delta_points = (
            float(current_points_num) - float(points_cutoff)
            if isinstance(current_points_num, (int, float)) and isinstance(points_cutoff, (int, float))
            else None
        )
        payout_cents = _to_int(
            row.get("payout_cents") if row.get("payout_cents") is not None else standings_row.get("payout_cents")
        )
        if isinstance(payout_cents, int):
            is_cashing = payout_cents > 0
        else:
            is_cashing = bool(row.get("is_cashing")) if isinstance(row.get("is_cashing"), bool) else bool(
                standings_row.get("is_cashing")
            )

        mapped = {
            "display_name": display_name,
            "entry_key": entry_key,
            "vip_entry_key": row.get("vip_entry_key"),
            "live": {
                "updated_at": updated_at,
                "current_points": current_points_num,
                "current_rank": current_rank_num,
                "cash_line_delta_points": cash_line_delta_points,
                "is_cashing": is_cashing,
                "payout_cents": payout_cents,
                "ownership_remaining_pct": _to_float(standings_row.get("ownership_remaining_pct")),
                "pmr": _to_float(row.get("pmr") if row.get("pmr") is not None else standings_row.get("pmr")),
            },
            "slots": _vip_slots_from_lineup(
                row.get("lineup") if row.get("lineup") is not None else row.get("players"),
                player_lookup,
            ),
            "players_live": _vip_players_live_from_lineup(
                row.get("players") if row.get("players") is not None else row.get("lineup"),
                player_lookup,
                player_status_lookup,
            ),
        }
        normalized.append(mapped)
    return normalized


def _distance_to_cash_metrics(
    vip_lineups: list[dict[str, Any]],
    cash_line: dict[str, Any],
) -> dict[str, Any] | None:
    cutoff_points = cash_line.get("points_cutoff")
    rank_cutoff = cash_line.get("rank_cutoff")
    per_vip: list[dict[str, Any]] = []
    for lineup in vip_lineups:
        live = lineup.get("live") or {}
        current_points = live.get("current_points")
        current_rank = live.get("current_rank")
        points_delta = None
        if isinstance(current_points, (int, float)) and isinstance(cutoff_points, (int, float)):
            points_delta = float(current_points) - float(cutoff_points)
        rank_delta = None
        if isinstance(current_rank, int) and isinstance(rank_cutoff, int):
            rank_delta = int(rank_cutoff) - int(current_rank)
        if points_delta is None and rank_delta is None:
            continue
        row = {
            "vip_entry_key": lineup.get("vip_entry_key"),
            "entry_key": lineup.get("entry_key"),
            "display_name": lineup.get("display_name"),
        }
        if points_delta is not None:
            row["points_delta"] = points_delta
        if rank_delta is not None:
            row["rank_delta"] = rank_delta
        per_vip.append(row)

    if not per_vip:
        return None

    metrics: dict[str, Any] = {
        "per_vip": per_vip,
    }
    if isinstance(cutoff_points, (int, float)):
        metrics["cutoff_points"] = cutoff_points
    return metrics


def _normalize_status_text(value: Any) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return ""
    return " ".join(text.split())


def _status_bucket(value: Any) -> str:
    normalized = _normalize_status_text(value)
    if not normalized:
        return "unknown"
    if normalized.startswith("final"):
        return "terminal"
    if normalized in {"complete", "completed", "closed", "canceled", "cancelled", "postponed", "suspended"}:
        return "terminal"
    if normalized in {"scheduled", "in progress", "live", "pregame", "halftime"}:
        return "active"
    return "unknown"


def _ownership_summary_metrics(vip_lineups: list[dict[str, Any]]) -> dict[str, Any] | None:
    per_vip: list[dict[str, Any]] = []
    for lineup in vip_lineups:
        vip_entry_key = lineup.get("vip_entry_key")
        entry_key = lineup.get("entry_key")
        if vip_entry_key in (None, "") and entry_key in (None, ""):
            continue

        players_live = lineup.get("players_live") or []
        total_ownership = 0.0
        ownership_in_play = 0.0
        has_total_input = False
        has_in_play_input = False
        is_partial = False

        for player in players_live:
            if not isinstance(player, dict):
                continue
            ownership = player.get("ownership_pct")
            if not isinstance(ownership, (int, float)):
                is_partial = True
                continue

            ownership_value = float(ownership)
            total_ownership += ownership_value
            has_total_input = True

            status_bucket = _status_bucket(player.get("game_status"))
            if status_bucket == "active":
                ownership_in_play += ownership_value
                has_in_play_input = True
            elif status_bucket == "terminal":
                has_in_play_input = True
            else:
                is_partial = True

        if not has_total_input:
            is_partial = True

        row: dict[str, Any] = {
            "vip_entry_key": vip_entry_key,
            "entry_key": entry_key,
            "display_name": lineup.get("display_name"),
            "is_partial": is_partial,
        }
        if has_total_input:
            row["total_ownership_pct"] = round(total_ownership, 4)
        if has_in_play_input:
            row["ownership_in_play_pct"] = round(ownership_in_play, 4)
        per_vip.append(row)

    if not per_vip:
        return None

    return {
        "source": "vip_lineup_players",
        "scope": "vip_lineup",
        "per_vip": per_vip,
    }


def _non_cashing_metrics(ownership_source: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(ownership_source, dict):
        return None

    users_not_cashing = _rank_numeric(ownership_source.get("non_cashing_user_count"))
    avg_pmr_remaining = _to_float(ownership_source.get("non_cashing_avg_pmr"))
    top_source = ownership_source.get("top_remaining_players") or []

    top_remaining_players: list[dict[str, Any]] = []
    for row in top_source:
        if not isinstance(row, dict):
            continue
        player_name = row.get("player_name") or row.get("display_name") or row.get("entry_key")
        if player_name in (None, ""):
            continue
        player_row: dict[str, Any] = {
            "player_name": player_name,
        }
        ownership_pct = _to_float(row.get("ownership_remaining_pct"))
        if isinstance(ownership_pct, (int, float)):
            player_row["ownership_remaining_pct"] = ownership_pct
        top_remaining_players.append(player_row)

    has_non_default = (
        (isinstance(users_not_cashing, int) and users_not_cashing > 0)
        or (isinstance(avg_pmr_remaining, (int, float)) and float(avg_pmr_remaining) > 0)
        or len(top_remaining_players) > 0
    )
    if not has_non_default:
        return None

    metrics: dict[str, Any] = {}
    if users_not_cashing is not None:
        metrics["users_not_cashing"] = users_not_cashing
    if avg_pmr_remaining is not None:
        metrics["avg_pmr_remaining"] = avg_pmr_remaining
    if top_remaining_players:
        metrics["top_remaining_players"] = top_remaining_players
    return metrics


def _threat_metrics(
    ownership_watchlist: dict[str, Any] | None,
    vip_lineups: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if not ownership_watchlist:
        return None

    entries = ownership_watchlist.get("entries") or []
    total_pct = ownership_watchlist.get("ownership_remaining_total_pct")
    if isinstance(total_pct, (int, float)):
        field_remaining_pct = float(total_pct)
        field_remaining_source = "ownership_watchlist_total"
        field_remaining_is_partial = False
    else:
        values = [
            entry.get("ownership_remaining_pct")
            for entry in entries
            if isinstance(entry.get("ownership_remaining_pct"), (int, float))
        ]
        field_remaining_pct = float(sum(values)) if values else None
        field_remaining_source = "watchlist_entries_sum"
        field_remaining_is_partial = True

    vip_lineup_players: list[set[str]] = []
    for lineup in vip_lineups:
        slots = lineup.get("slots") or []
        names = {str(slot.get("player_name")).strip().lower() for slot in slots if slot.get("player_name")}
        vip_lineup_players.append(names)

    top_swing: list[dict[str, Any]] = []
    for entry in sorted(
        entries,
        key=lambda item: item.get("ownership_remaining_pct") or 0,
        reverse=True,
    ):
        name = entry.get("display_name") or entry.get("entry_key")
        if not name:
            continue
        name_key = str(name).strip().lower()
        vip_count = sum(1 for names in vip_lineup_players if name_key in names)
        top_swing.append(
            {
                "player_name": name,
                "remaining_ownership_pct": entry.get("ownership_remaining_pct"),
                "vip_count": vip_count,
            }
        )

    vip_vs_field: list[dict[str, Any]] = []
    for lineup in vip_lineups:
        vip_remaining = (lineup.get("live") or {}).get("ownership_remaining_pct")
        uniqueness_delta = None
        if isinstance(field_remaining_pct, (int, float)) and isinstance(vip_remaining, (int, float)):
            uniqueness_delta = float(field_remaining_pct) - float(vip_remaining)
        vip_vs_field.append(
            {
                "vip_entry_key": lineup.get("vip_entry_key"),
                "entry_key": lineup.get("entry_key"),
                "display_name": lineup.get("display_name"),
                "vip_remaining_pct": vip_remaining,
                "field_remaining_pct": field_remaining_pct,
                "uniqueness_delta_pct": uniqueness_delta,
            }
        )

    if not top_swing and not vip_vs_field and field_remaining_pct is None:
        return None

    return {
        "leverage_semantics": "positive=unique",
        "field_remaining_scope": "watchlist",
        "field_remaining_source": field_remaining_source,
        "field_remaining_is_partial": field_remaining_is_partial,
        "field_remaining_pct": field_remaining_pct,
        "top_swing_players": top_swing,
        "vip_vs_field_leverage": vip_vs_field,
    }


def _train_metrics(train_clusters: dict[str, Any] | None) -> dict[str, Any] | None:
    if not train_clusters:
        return None
    clusters = train_clusters.get("clusters") or []
    if not clusters:
        return None

    def _rank_key(cluster: dict[str, Any]) -> tuple[float, int, float, str]:
        best_rank = cluster.get("best_rank")
        best_rank = float(best_rank) if isinstance(best_rank, (int, float)) else float("inf")
        entry_count = cluster.get("entry_count")
        entry_count = int(entry_count) if isinstance(entry_count, int) else 0
        avg_pmr = cluster.get("avg_pmr")
        avg_pmr = float(avg_pmr) if isinstance(avg_pmr, (int, float)) else float("inf")
        cluster_key = cluster.get("cluster_key") or ""
        return (best_rank, -entry_count, avg_pmr, str(cluster_key))

    ranked = sorted(clusters, key=_rank_key)
    ranked_clusters = [
        {
            "cluster_key": cluster.get("cluster_key"),
            "rank": index + 1,
            "entry_count": cluster.get("entry_count"),
            "best_rank": cluster.get("best_rank"),
            "avg_pmr": cluster.get("avg_pmr"),
        }
        for index, cluster in enumerate(ranked)
    ]
    top_n = 5
    return {
        "recommended_top_n": top_n,
        "ranked_clusters": ranked_clusters,
        "top_clusters": ranked_clusters[:top_n],
    }


def _selection_reason_text(reason: Any, contest_id: Any) -> str | None:
    if isinstance(reason, str):
        text = reason.strip()
        return text if text else None
    if isinstance(reason, dict):
        mode = str(reason.get("mode") or "unknown")
        if mode == "explicit_id":
            return f"explicit_id contest_id={contest_id}"
        return mode
    if reason is None:
        return None
    return str(reason)


def _dollars_to_cents_half_up(value: Any) -> int | None:
    if value in (None, ""):
        return None
    text = str(value).strip().replace("$", "").replace(",", "")
    if not text:
        return None
    try:
        dollars = Decimal(text)
    except InvalidOperation:
        return None
    cents = (dollars * Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(cents)


def _leaderboard_row_payout_cents(row: dict[str, Any]) -> int | None:
    winning_value_cents = _dollars_to_cents_half_up(row.get("winningValue"))
    if winning_value_cents is not None:
        return winning_value_cents

    winnings = row.get("winnings")
    if not isinstance(winnings, list):
        return None

    total_cents = 0
    found_cash = False
    for item in winnings:
        if not isinstance(item, dict):
            continue
        description = str(item.get("description") or "").strip().lower()
        if "cash" not in description:
            continue
        item_cents = _dollars_to_cents_half_up(item.get("value"))
        if item_cents is None:
            continue
        found_cash = True
        total_cents += item_cents
    return total_cents if found_cash else None


def _leaderboard_payout_map(payload: dict[str, Any]) -> dict[str, int]:
    rows = payload.get("leaderBoard")
    if not isinstance(rows, list):
        return {}

    payout_by_entry: dict[str, int] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        entry_key = row.get("entryKey")
        if entry_key in (None, ""):
            continue
        payout_cents = _leaderboard_row_payout_cents(row)
        if payout_cents is None:
            continue
        payout_by_entry[str(entry_key)] = payout_cents
    return payout_by_entry


def _money_to_cents(value: Any) -> int | None:
    if value in (None, ""):
        return None
    if isinstance(value, int):
        return value * 100
    if isinstance(value, float):
        return int(round(value * 100))
    text = str(value).strip()
    if not text:
        return None
    text = text.replace("$", "").replace(",", "")
    try:
        numeric = float(text)
    except ValueError:
        return None
    return int(round(numeric * 100))


def _normalize_contest_state(raw_state: Any, completed: Any) -> str | None:
    if completed in (1, True, "1", "true", "True"):
        return "completed"
    text = _normalize_status_text(raw_state)
    if not text:
        return None
    if text in {"scheduled", "upcoming", "pregame", "pre-game", "not started"}:
        return "upcoming"
    if text in {"live", "in progress", "in-progress", "started"}:
        return "live"
    if text in {"complete", "completed", "closed", "final"}:
        return "completed"
    if text in {"canceled", "cancelled", "postponed", "suspended"}:
        return "cancelled"
    return None


def _canonical_contest_contract(
    contest: dict[str, Any],
    *,
    sport: str,
) -> dict[str, Any]:
    contest_id_value = contest.get("contest_id")
    contest_id = str(contest_id_value) if contest_id_value not in (None, "") else None
    sport_text = str(contest.get("sport") or sport or "").strip().lower()
    contest_key = contest.get("contest_key")
    if contest_key in (None, "") and sport_text and contest_id:
        contest_key = f"{sport_text}:{contest_id}"

    start_time = to_utc_iso(contest.get("start_time")) or to_utc_iso(contest.get("start_time_utc"))
    entry_fee_cents = _to_int_flexible(contest.get("entry_fee_cents"))
    if entry_fee_cents is None:
        entry_fee_cents = _money_to_cents(contest.get("entry_fee"))
    prize_pool_cents = _to_int_flexible(contest.get("prize_pool_cents"))
    if prize_pool_cents is None:
        prize_pool_cents = _to_int_flexible(contest.get("payout_cents"))
    if prize_pool_cents is None:
        prize_pool_cents = _money_to_cents(contest.get("prize_pool"))

    entries_count = _to_int_flexible(contest.get("entries_count"))
    max_entries = _to_int_flexible(contest.get("max_entries"))
    if max_entries is None:
        max_entries = _to_int_flexible(contest.get("entries"))
    max_entries_per_user = _to_int_flexible(contest.get("max_entries_per_user"))
    if max_entries_per_user is None:
        max_entries_per_user = _to_int_flexible(contest.get("max_entry_count"))

    contest_type_raw = contest.get("contest_type")
    contest_type = str(contest_type_raw).strip() if contest_type_raw not in (None, "") else None
    state = _normalize_contest_state(contest.get("state"), contest.get("completed"))
    currency_raw = contest.get("currency")
    currency = str(currency_raw).strip() if currency_raw not in (None, "") else None
    name_raw = contest.get("name")
    name = str(name_raw).strip() if name_raw not in (None, "") else None

    canonical: dict[str, Any] = dict(contest)
    canonical.update(
        {
            "contest_id": contest_id,
            "contest_key": str(contest_key) if contest_key not in (None, "") else None,
            "name": name,
            "sport": sport_text,
            "contest_type": contest_type,
            "start_time": start_time,
            "state": state,
            "entry_fee_cents": entry_fee_cents,
            "prize_pool_cents": prize_pool_cents,
            "currency": currency,
            "max_entries": max_entries,
            "max_entries_per_user": max_entries_per_user,
        }
    )
    if entries_count is None:
        canonical.pop("entries_count", None)
    else:
        canonical["entries_count"] = entries_count
    canonical.pop("entries", None)
    canonical.pop("start_time_utc", None)
    return canonical


def build_dashboard_sport_snapshot(snapshot: dict[str, Any], generated_at: str) -> dict[str, Any]:
    normalized = normalize_snapshot_for_output(snapshot)
    updated_at = normalized.get("snapshot_generated_at_utc") or generated_at
    contest = dict(normalized.get("contest") or {})
    selection = dict(normalized.get("selection") or {})
    contest_id = selection.get("selected_contest_id") or contest.get("contest_id")
    truncation = dict(normalized.get("truncation") or {})
    players = list(normalized.get("players") or [])
    player_lookup = _build_player_name_lookup(players)
    player_status_lookup = _build_player_status_lookup(players)
    standings_rows = list(normalized.get("standings") or [])
    standings_rows = _normalize_standings_rows(standings_rows)
    standings_by_entry_key = {
        str(row.get("entry_key")): row
        for row in standings_rows
        if isinstance(row, dict) and row.get("entry_key") not in (None, "")
    }
    standings_by_username = _unique_standings_by_display_name(standings_rows)

    contest_object = _canonical_contest_contract(contest, sport=str(normalized.get("sport") or ""))
    contest_object["is_primary"] = True
    for key in (
        "entries_count",
        "max_entries",
        "positions_paid",
        "entry_fee_cents",
        "prize_pool_cents",
        "draft_group",
    ):
        if key in contest_object:
            contest_object[key] = _rank_numeric(contest_object.get(key))
    cash_line = _cash_line_contract(dict(normalized.get("cash_line") or {}))

    ownership_source = normalized.get("ownership")
    if isinstance(ownership_source, dict):
        contest_object["ownership_watchlist"] = _ownership_watchlist_contract(
            ownership_source,
            updated_at,
        )

    if isinstance(normalized.get("standings"), list):
        contest_object["standings"] = {
            "updated_at": updated_at,
            "rows": standings_rows,
            "total_rows": truncation.get("total_rows_before_truncation")
            or truncation.get("total_rows_after_truncation")
            or len(standings_rows),
            "is_truncated": bool(truncation.get("applied")),
        }

    train_source = normalized.get("train_clusters")
    if isinstance(train_source, list):
        contest_object["train_clusters"] = _train_clusters_contract(
            train_source,
            updated_at,
            player_lookup,
            standings_by_entry_key,
        )

    vip_source = normalized.get("vip_lineups")
    if isinstance(vip_source, list):
        contest_object["vip_lineups"] = _vip_lineups_contract(
            vip_source,
            player_lookup,
            player_status_lookup,
            updated_at,
            standings_by_entry_key,
            standings_by_username,
            cash_line,
        )
    metrics: dict[str, Any] = {}
    if "vip_lineups" in contest_object:
        distance_to_cash = _distance_to_cash_metrics(
            contest_object["vip_lineups"],
            cash_line,
        )
        if distance_to_cash:
            metrics["distance_to_cash"] = distance_to_cash
        ownership_summary = _ownership_summary_metrics(contest_object["vip_lineups"])
        if ownership_summary:
            metrics["ownership_summary"] = ownership_summary
    threat = _threat_metrics(
        contest_object.get("ownership_watchlist"),
        contest_object.get("vip_lineups", []),
    )
    if threat:
        metrics["threat"] = threat
    non_cashing = _non_cashing_metrics(ownership_source if isinstance(ownership_source, dict) else None)
    if non_cashing:
        metrics["non_cashing"] = non_cashing
    trains = _train_metrics(contest_object.get("train_clusters"))
    if trains:
        metrics["trains"] = trains
    if metrics:
        contest_object["metrics"] = {"updated_at": updated_at, **metrics}
    contest_object["live_metrics"] = {
        "updated_at": updated_at,
        "cash_line": cash_line,
    }
    contest_object.pop("ownership", None)
    contest_object.pop("selection", None)
    contest_object.pop("truncation", None)
    contest_object.pop("metadata", None)
    contest_object.pop("snapshot_version", None)
    contest_object.pop("snapshot_generated_at_utc", None)

    sport_snapshot: dict[str, Any] = {
        "status": normalized.get("status") or "ok",
        "updated_at": updated_at,
        "players": players,
        "contests": [contest_object],
    }
    if contest_id is not None:
        sport_snapshot["primary_contest"] = {
            "contest_id": contest_id,
            "contest_key": contest_object.get("contest_key"),
            "selection_reason": _selection_reason_text(selection.get("reason"), contest_id),
            "selected_at": generated_at,
        }
    error = normalized.get("error")
    if error not in (None, ""):
        sport_snapshot["error"] = error
    return sport_snapshot


def build_dashboard_envelope(sports: dict[str, dict[str, Any]]) -> dict[str, Any]:
    generated_at = to_utc_iso(datetime.datetime.now(datetime.timezone.utc))
    if generated_at is None:
        raise RuntimeError("Failed to build generated_at timestamp")
    output_sports: dict[str, Any] = {}
    for sport, snapshot in sorted(sports.items()):
        sport_snapshot = build_dashboard_sport_snapshot(snapshot, generated_at)
        output_sports[sport.lower()] = sport_snapshot
    return {
        "schema_version": 2,
        "snapshot_at": generated_at,
        "generated_at": generated_at,
        "sports": output_sports,
    }


def is_dashboard_envelope(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False

    # Legacy/raw payload roots are not part of the dashboard envelope contract.
    legacy_root_keys = {"contest", "selection", "vip_lineups", "standings", "cash_line"}
    if any(key in payload for key in legacy_root_keys):
        return False

    sports = payload.get("sports")
    if not isinstance(sports, dict):
        return False

    for sport_payload in sports.values():
        if not isinstance(sport_payload, dict):
            return False
        if not isinstance(sport_payload.get("contests"), list):
            return False
        if not isinstance(sport_payload.get("players"), list):
            return False

    return True


def _is_numeric_string(value: str) -> bool:
    text = value.strip()
    if not text:
        return False
    try:
        float(text)
    except ValueError:
        return False
    return True


def _walk_paths(value: Any, path: str = "") -> list[tuple[str, Any]]:
    items: list[tuple[str, Any]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else key
            items.extend(_walk_paths(child, child_path))
        return items
    if isinstance(value, list):
        for idx, child in enumerate(value):
            child_path = f"{path}.{idx}" if path else str(idx)
            items.extend(_walk_paths(child, child_path))
        return items
    items.append((path, value))
    return items


def validate_canonical_snapshot(payload: dict[str, Any]) -> list[str]:
    violations: list[str] = []
    allowed_numeric_string_suffixes = (
        ".contest_id",
        ".contest_key",
        ".entry_key",
        ".vip_entry_key",
        ".cluster_key",
        ".selection_reason",
        ".display_name",
        ".time_remaining_display",
    )

    for path, value in _walk_paths(payload):
        if not path:
            continue
        key = path.split(".")[-1]
        if key in CANONICAL_DISALLOWED_KEYS:
            violations.append(f"disallowed_key:{path}")
        if key == "start_time_utc":
            violations.append(f"disallowed_key:{path}")
        if isinstance(value, str) and _is_numeric_string(value):
            if not path.endswith(allowed_numeric_string_suffixes):
                violations.append(f"numeric_string:{path}")

    required_contest_fields: dict[str, type] = {
        "contest_id": str,
        "contest_key": str,
        "name": str,
        "sport": str,
        "contest_type": str,
        "start_time": str,
        "state": str,
        "entry_fee_cents": int,
        "prize_pool_cents": int,
        "currency": str,
        "max_entries": int,
        "max_entries_per_user": int,
    }
    valid_states = {"upcoming", "live", "completed", "cancelled"}
    sports = payload.get("sports")
    if isinstance(sports, dict):
        for sport_key, sport_payload in sports.items():
            if not isinstance(sport_payload, dict):
                continue
            contests = sport_payload.get("contests") or []
            if not isinstance(contests, list):
                continue
            selected_contest: dict[str, Any] | None = None
            for idx, contest in enumerate(contests):
                if not isinstance(contest, dict):
                    violations.append(f"invalid_type:sports.{sport_key}.contests.{idx}")
                    continue
                path_prefix = f"sports.{sport_key}.contests.{idx}"
                for field_name, expected_type in required_contest_fields.items():
                    value = contest.get(field_name)
                    if value is None:
                        violations.append(f"missing_required:{path_prefix}.{field_name}")
                        continue
                    if type(value) is not expected_type:
                        violations.append(f"type_mismatch:{path_prefix}.{field_name}")
                if "entries_count" in contest:
                    entries_count = contest.get("entries_count")
                    if entries_count is None:
                        violations.append(f"type_mismatch:{path_prefix}.entries_count")
                    elif type(entries_count) is not int:
                        violations.append(f"type_mismatch:{path_prefix}.entries_count")
                start_time_value = contest.get("start_time")
                if isinstance(start_time_value, str) and to_utc_iso(start_time_value) is None:
                    violations.append(f"invalid_datetime:{path_prefix}.start_time")
                state_value = contest.get("state")
                if isinstance(state_value, str) and state_value not in valid_states:
                    violations.append(f"invalid_value:{path_prefix}.state")
                if selected_contest is None and contest.get("is_primary") is True:
                    selected_contest = contest
            if selected_contest is None and contests:
                first_contest = contests[0]
                if isinstance(first_contest, dict):
                    selected_contest = first_contest
            primary_contest = sport_payload.get("primary_contest")
            primary_path = f"sports.{sport_key}.primary_contest"
            if contests and not isinstance(primary_contest, dict):
                violations.append(f"missing_required:{primary_path}")
                continue
            if isinstance(primary_contest, dict):
                contest_key = primary_contest.get("contest_key")
                if contest_key in (None, ""):
                    violations.append(f"missing_required:{primary_path}.contest_key")
                if selected_contest is not None:
                    selected_key = selected_contest.get("contest_key")
                    if contest_key != selected_key:
                        violations.append(f"mismatch:{primary_path}.contest_key")
    return sorted(set(violations))
