from __future__ import annotations

import logging
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Protocol

import requests
import yaml

from dk_results.paths import repo_file

logger = logging.getLogger(__name__)


# ── Protocol ──────────────────────────────────────────────────────────────────


class DkHttpPort(Protocol):
    def get_leaderboard(self, contest_id: int, *, timeout: int | None = None) -> dict[str, Any]: ...
    def get_entry(
        self, draft_group: int, entry_key: str, *, timeout: int | None = None, session: requests.Session | None = None
    ) -> dict[str, Any]: ...
    def clone_auth_to(self, target_session: requests.Session) -> None: ...


# ── Domain types ──────────────────────────────────────────────────────────────


@dataclass
class VipPlayer:
    pos: str
    name: str
    pts: str
    salary: int | None
    value: str
    ownership: float | str
    rt_proj: str
    pregame_proj: str | float
    time_status: str
    value_icon: str
    stats: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "pos": self.pos,
            "name": self.name,
            "pts": self.pts,
            "salary": self.salary if self.salary is not None else "",
            "value": self.value,
            "ownership": self.ownership,
            "rtProj": self.rt_proj,
            "pregameProj": self.pregame_proj,
            "timeStatus": self.time_status,
            "valueIcon": self.value_icon,
            "stats": self.stats,
        }


@dataclass
class VipLineup:
    user: str
    rank: str
    pts: str
    pmr: str
    entry_key: str
    total_salary: int
    players: list[VipPlayer] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "user": self.user,
            "rank": self.rank,
            "pts": self.pts,
            "pmr": self.pmr,
            "entry_key": self.entry_key,
            "salary": self.total_salary,
            "players": [p.to_dict() for p in self.players],
        }


# ── vips.yaml loading ─────────────────────────────────────────────────────────


def load_vips() -> list[str]:
    """Load VIP usernames from vips.yaml located next to this file."""
    vip_path = repo_file("vips.yaml")
    try:
        with open(vip_path, "r") as f:
            vips = yaml.safe_load(f) or []
        if not isinstance(vips, list):
            logger.warning("vips.yaml did not contain a list; treating as empty.")
            return []
        return [str(x).strip() for x in vips if str(x).strip()]
    except FileNotFoundError:
        logger.warning("vips.yaml not found at %s; proceeding with empty VIP list.", vip_path)
        return []
    except Exception as e:
        logger.warning("Failed to load vips.yaml: %s; proceeding with empty VIP list.", e)
        return []


# ── vip_entries construction ──────────────────────────────────────────────────


def build_vip_entries(vip_list: list[Any]) -> dict[str, dict[str, Any]]:
    """Convert results.vip_list to the entry-key map consumed by fetch_vip_lineups."""
    entries: dict[str, dict[str, Any]] = {}
    for vip in vip_list:
        if not vip.name or not vip.player_id:
            continue
        entries[vip.name] = {
            "entry_key": vip.player_id,
            "pmr": vip.pmr,
            "rank": vip.rank,
            "pts": vip.pts,
        }
    return entries


# ── Salary helpers ────────────────────────────────────────────────────────────


def _normalize_name(name: str) -> str:
    if not isinstance(name, str):
        return ""
    return "".join(c for c in unicodedata.normalize("NFD", name) if unicodedata.category(c) != "Mn")


def _lookup_salary(player_name: str, player_salary_map: dict[str, int] | None) -> int | None:
    if not player_salary_map or not player_name:
        return None
    clean = player_name.strip()
    if not clean:
        return None
    if clean in player_salary_map:
        return player_salary_map[clean]
    normalized = _normalize_name(clean)
    if normalized in player_salary_map:
        return player_salary_map[normalized]
    return None


# ── Scorecard parsing ─────────────────────────────────────────────────────────


def _parse_scorecard(
    scorecard_js: dict[str, Any],
    player_salary_map: dict[str, int] | None,
) -> tuple[list[VipPlayer], int]:
    entries = scorecard_js.get("entries", [])
    if not entries:
        return [], 0
    roster = entries[0].get("roster", {})
    scorecards = roster.get("scorecards", [])
    players: list[VipPlayer] = []
    total_salary = 0

    for sc in scorecards:
        projection = sc.get("projection", {}) or {}
        percent = sc.get("percentDrafted")
        ownership: float | str = float(percent) / 100 if percent not in (None, "") else ""
        display_name = sc.get("displayName", "") or "LOCKED 🔒"

        salary_val = _lookup_salary(display_name, player_salary_map)
        if salary_val is None:
            salary_raw = sc.get("salary")
            if salary_raw not in (None, ""):
                try:
                    salary_val = int(float(salary_raw))
                except (TypeError, ValueError):
                    pass
        if salary_val is not None:
            total_salary += salary_val

        pts_raw = sc.get("score", "") or ""
        value = ""
        if salary_val is not None:
            try:
                pts_val = float(pts_raw)
                if pts_val:
                    value = f"{pts_val / (salary_val / 1000):.2f}"
            except (TypeError, ValueError, ZeroDivisionError):
                pass

        rt_proj_raw = projection.get("realTimeProjection", "")
        rt_proj = ""
        if rt_proj_raw not in (None, ""):
            try:
                rt_proj = f"{float(rt_proj_raw):.2f}"
            except (TypeError, ValueError):
                rt_proj = str(rt_proj_raw)

        players.append(
            VipPlayer(
                pos=sc.get("rosterPosition", "") or "",
                name=display_name,
                pts=str(pts_raw),
                salary=salary_val,
                value=value,
                ownership=ownership,
                rt_proj=rt_proj,
                pregame_proj=projection.get("pregameProjection", ""),
                time_status=str(sc.get("timeRemaining", "") or ""),
                value_icon=projection.get("valueIcon", "") or "",
                stats=sc.get("statsDescription", "") or "",
            )
        )

    return players, total_salary


# ── Worker ────────────────────────────────────────────────────────────────────


def _fetch_one(
    http: DkHttpPort,
    user_dict: dict[str, Any],
    draft_group: int,
    player_salary_map: dict[str, int] | None,
    timeout: int | None,
) -> VipLineup | None:
    entry_key = user_dict.get("entryKey") or user_dict.get("entry_key")
    if not entry_key:
        return None

    thread_sess = requests.Session()
    http.clone_auth_to(thread_sess)
    scorecard_js = http.get_entry(draft_group, str(entry_key), timeout=timeout, session=thread_sess)
    players, total_salary = _parse_scorecard(scorecard_js, player_salary_map)
    if not players:
        return None

    return VipLineup(
        user=user_dict.get("userName", ""),
        rank=str(user_dict.get("rank", "")),
        pts=str(user_dict.get("fantasyPoints", "") or user_dict.get("pts", "")),
        pmr=str(user_dict.get("timeRemaining", "") or user_dict.get("pmr", "")),
        entry_key=str(entry_key),
        total_salary=total_salary,
        players=players,
    )


# ── Public interface ──────────────────────────────────────────────────────────


def fetch_vip_lineups(
    contest_id: int,
    draft_group: int,
    http: DkHttpPort,
    *,
    vips: list[str] | None = None,
    vip_entries: dict[str, dict[str, Any]] | None = None,
    player_salary_map: dict[str, int] | None = None,
    timeout: int | None = None,
    max_workers: int = 8,
) -> list[VipLineup]:
    """
    Fetch VIP lineups concurrently and return typed VipLineup objects.

    Provide vip_entries (name -> {entry_key, pmr, rank, pts}) when entry keys are
    already known from standings. Otherwise provide vips (list of usernames) and
    the leaderboard is queried and filtered.
    """
    users_to_fetch: list[dict[str, Any]] = []

    if vip_entries:
        for vip_name, entry_data in vip_entries.items():
            if isinstance(entry_data, dict):
                entry_key = entry_data.get("entry_key") or entry_data.get("entryKey")
                pmr = entry_data.get("pmr", "")
                rank = entry_data.get("rank", "")
                pts = entry_data.get("pts", "")
            else:
                entry_key = entry_data
                pmr = rank = pts = ""
            if not entry_key:
                continue
            users_to_fetch.append(
                {
                    "userName": vip_name,
                    "entryKey": entry_key,
                    "timeRemaining": pmr,
                    "rank": rank,
                    "fantasyPoints": pts,
                }
            )
    else:
        lb = http.get_leaderboard(contest_id, timeout=timeout)
        vip_set = set(vips or [])
        users_to_fetch = [u for u in lb.get("leaderBoard", []) if u.get("userName") in vip_set]

    if not users_to_fetch:
        logger.debug("No VIP entries found to fetch.")
        return []

    n_workers = min(max_workers, len(users_to_fetch)) or 1
    lineups: list[VipLineup] = []
    missing_roster = 0
    failures = 0

    with ThreadPoolExecutor(max_workers=n_workers) as executor:
        futures = {
            executor.submit(_fetch_one, http, u, draft_group, player_salary_map, timeout): u for u in users_to_fetch
        }
        for fut in as_completed(futures):
            user = futures[fut].get("userName", "<unknown>")
            try:
                result = fut.result()
                if result is None:
                    missing_roster += 1
                    logger.debug("VIP %s had no roster data", user)
                else:
                    logger.debug("Found VIP lineup for user %s", result.user)
                    lineups.append(result)
            except Exception as e:
                failures += 1
                try:
                    logger.error("Failed fetching lineup for %s: %s", user, e)
                except Exception:
                    pass

    logger.info(
        "vip_lineups_fetch contest_id=%s draft_group=%s requested=%d found=%d missing_roster=%d failures=%d",
        contest_id,
        draft_group,
        len(users_to_fetch),
        len(lineups),
        missing_roster,
        failures,
    )
    return lineups
