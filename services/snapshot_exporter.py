import copy
import datetime
import hashlib
import json
import logging
import os
import pathlib
from typing import Any

import yaml
from zoneinfo import ZoneInfo

from dfs_common import config as common_config
from dfs_common import state
from classes.contestdatabase import ContestDatabase
from classes.draftkings import Draftkings
from classes.results import Results
from classes.sport import Sport
from classes.trainfinder import TrainFinder

logger = logging.getLogger(__name__)

CONTEST_DIR = "contests"
SALARY_DIR = "salary"
SALARY_LIMIT = 40000
COOKIES_FILE = "pickled_cookies_works.txt"
CANDIDATE_LIMIT = 5
DEFAULT_STANDINGS_LIMIT = 500

ID_FIELDS = {
    "contest_id",
    "draft_group",
    "selected_contest_id",
    "entry_key",
    "cluster_id",
}

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
    vip_path = pathlib.Path(__file__).resolve().parent.parent / "vips.yaml"
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
    cfg = common_config.load_json_config()
    settings = common_config.resolve_dk_results_settings(cfg)
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
    return (
        dk_id,
        contest_detail.get("name"),
        contest_detail.get("draftGroupId"),
        positions_paid,
        start_time,
        contest_detail.get("entryFee"),
        contest_detail.get("maximumEntries"),
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
                selected = _contest_row_from_detail(
                    int(contest_id), dk.get_contest_detail(int(contest_id))
                )
        else:
            if contest_db is None:
                raise RuntimeError("Contest DB unavailable for primary live selection")
            live = contest_db.get_live_contest(
                sport_cls.name, sport_cls.sheet_min_entry_fee, sport_cls.keyword
            )
            if live:
                selected = contest_db.get_contest_by_id(int(live[0]))

        if not selected:
            raise RuntimeError(f"No contest found for sport={sport_cls.name}")

        dk_id, contest_name, draft_group, positions_paid, start_date, entry_fee, entries = (
            selected
        )
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
        for user in results.users:
            parsed_rank = _rank_numeric(user.rank)
            standings.append(
                {
                    "rank": parsed_rank if parsed_rank is not None else user.rank,
                    "entry_key": user.player_id,
                    "username": user.name,
                    "pmr": _to_float(user.pmr),
                    "points": _to_float(user.pts),
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
        ownership_remaining_total = (
            sum(ownership_values) / len(ownership_values) if ownership_values else None
        )

        top_remaining_players: list[dict[str, Any]] = []
        if results.non_cashing_users > 0:
            for name, count in results.non_cashing_players.items():
                top_remaining_players.append(
                    {
                        "player_name": name,
                        "ownership_remaining_pct": (float(count) / results.non_cashing_users)
                        * 100,
                    }
                )
        top_remaining_players.sort(
            key=lambda item: (-item["ownership_remaining_pct"], item["player_name"])
        )
        top_remaining_players = top_remaining_players[:10]

        cash_rank = results.min_rank if results.min_rank > 0 else None
        cash_points = results.min_cash_pts if cash_rank is not None else None
        cash_delta = None
        if cash_rank is not None:
            below_cash = [
                row
                for row in standings
                if _rank_numeric(row["rank"]) is not None
                and _rank_numeric(row["rank"]) > int(cash_rank)
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
                -(item["points"] if item["points"] is not None else -10**9),
                item["lineup_signature"],
            )
        )

        return {
            "sport": sport_cls.name,
            "contest": {
                "contest_id": dk_id,
                "name": contest_name,
                "draft_group": draft_group,
                "start_time_utc": to_utc_iso(start_date),
                "is_primary": True,
                "entry_fee": entry_fee,
                "entries": entries,
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
    snapshot["snapshot_generated_at_utc"] = to_utc_iso(
        datetime.datetime.now(datetime.timezone.utc)
    )

    missing = [
        path
        for path in _find_missing_fields(snapshot)
        if not path.startswith("metadata.missing_fields")
    ]
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
            _normalize_value(item, f"{path}.{idx}" if path else str(idx), warnings)
            for idx, item in enumerate(value)
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
    return json.dumps(
        payload,
        sort_keys=True,
        indent=2,
        separators=(",", ":"),
        ensure_ascii=True,
    ) + "\n"
