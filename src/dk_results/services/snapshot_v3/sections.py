"""Pure builders for snapshot-v3 collection sections.

Each function turns a parsed ``ContestStandings`` (plus already-derived VIP/payout
lookups) into one section of the raw source snapshot. They are deliberately free
of IO so the collector's orchestration can stay a readable top-to-bottom pipeline
and each section can be unit-tested in isolation.
"""

from __future__ import annotations

import hashlib
from typing import Any

from dk_results.analytics.contest_metrics import remaining_ownership
from dk_results.analytics.trainfinder import TrainFinder
from dk_results.domain.contest_standings import ContestStandings
from dk_results.services.snapshot_v3.normalize import to_float

SALARY_LIMIT = 40000


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


def _lineup_signature(user: Any) -> str:
    lineup_obj = getattr(user, "lineupobj", None)
    if not lineup_obj:
        return ""
    names = [getattr(player, "name", "").strip() for player in lineup_obj.lineup]
    return "|".join(names)


def _cluster_id_from_signature(signature: str) -> str:
    return hashlib.sha1(signature.encode("utf-8")).hexdigest()[:12]


def build_standings_rows(
    results: ContestStandings,
    *,
    leaderboard_payout_by_entry: dict[str, int],
    vip_lookup: set[str],
    vip_points_by_entry: dict[str, Any],
) -> list[dict[str, Any]]:
    """Build the sorted per-user standings rows (cashing, ownership, payout)."""
    standings: list[dict[str, Any]] = []
    cash_points_cutoff = results.min_cash_pts if results.min_rank > 0 else None
    for user in results.users:
        parsed_rank = _rank_numeric(user.rank)
        points = to_float(user.pts)
        entry_key = user.player_id
        payout_cents = leaderboard_payout_by_entry.get(str(entry_key), None) if entry_key else None
        is_vip = user.name in vip_lookup
        vip_points = vip_points_by_entry.get(str(entry_key)) if entry_key else None
        if is_vip and isinstance(vip_points, (int, float)) and isinstance(cash_points_cutoff, (int, float)):
            is_cashing = float(vip_points) >= float(cash_points_cutoff)
        elif isinstance(payout_cents, int):
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
                "ownership_remaining_total_pct": (
                    remaining_ownership(getattr(getattr(user, "lineupobj", None), "lineup", ()))
                    if getattr(user, "lineupobj", None)
                    else None
                ),
                "remaining_salary": user.salary,
                "is_vip": is_vip,
            }
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
    return standings


def build_players(results: ContestStandings) -> list[dict[str, Any]]:
    """Build the sorted player rows for the snapshot."""
    players: list[dict[str, Any]] = []
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
    return players


def build_top_remaining_players(results: ContestStandings) -> list[dict[str, Any]]:
    """Build the top-10 non-cashing player ownership rows."""
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
    return top_remaining_players[:10]


def build_watchlist(full_standings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build the top-10 watchlist ordered by remaining ownership."""
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
    return watchlist_entries[:10]


def build_cash_line(results: ContestStandings, full_standings: list[dict[str, Any]]) -> dict[str, Any]:
    """Build the cash-line summary (cutoff rank/points and delta to first-below)."""
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
    return {
        "cutoff_type": "positions_paid",
        "rank": cash_rank,
        "points": cash_points,
        "delta_to_cash": cash_delta,
    }


def build_train_clusters(results: ContestStandings) -> list[dict[str, Any]]:
    """Build the sorted train clusters (users sharing points/pmr above salary spent)."""
    trains = TrainFinder(results.users).get_users_above_salary_spent(SALARY_LIMIT)
    train_clusters: list[dict[str, Any]] = []
    for key, cluster in trains.items():
        if cluster.user_count <= 1:
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
                "user_count": cluster.user_count,
                "rank": cluster.rank,
                "points": to_float(cluster.points),
                "pmr": to_float(cluster.pmr),
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
    return train_clusters
