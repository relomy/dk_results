"""The source bundle from parsed standings and the resolved contest (pure).

Ownership remaining, field remaining and VIP remaining over the full standings,
standings truncation, the per-section builders' output, and the raw source-bundle
dict the collector returns.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, NamedTuple

from dk_results.analytics.contest_metrics import average_remaining_salary
from dk_results.analytics.game_status import is_locked_slot
from dk_results.domain.sport import Sport
from dk_results.services.snapshot_v3 import sections
from dk_results.services.snapshot_v3.contest_selection import (
    CANDIDATE_LIMIT,
    _build_selection_reason,
    _completed_at_for,
    _normalize_contest_state,
    _ResolvedContest,
    _summarize_candidates,
)
from dk_results.services.snapshot_v3.normalize import completed_at_field, to_float, to_utc_iso


def _build_vip_points_by_entry(
    vip_lineup_rows: list[dict[str, Any]],
    vip_list: list[Any],
) -> dict[str, float | None]:
    """Map entry key to VIP points, preferring lineup rows then falling back to the VIP list."""
    vip_points_by_entry: dict[str, float | None] = {
        str(row.get("vip_entry_key") or row.get("entry_key")): to_float(row.get("pts"))
        for row in vip_lineup_rows
        if (row.get("vip_entry_key") or row.get("entry_key")) not in (None, "") and to_float(row.get("pts")) is not None
    }
    for vip in vip_list:
        if vip.player_id not in (None, "") and str(vip.player_id) not in vip_points_by_entry:
            vip_points_by_entry[str(vip.player_id)] = to_float(vip.pts)
    return vip_points_by_entry


def _compute_ownership_remaining_total(full_standings: list[dict[str, Any]]) -> float | None:
    """Average the non-null remaining-ownership totals across standings rows."""
    ownership_values = [
        row["ownership_remaining_total_pct"]
        for row in full_standings
        if row["ownership_remaining_total_pct"] is not None
    ]
    if not ownership_values:
        return None
    return sum(ownership_values) / len(ownership_values)


class FieldRemaining(NamedTuple):
    """Contest-field remaining mean and whether any entry is incomplete."""

    pct: float | None
    is_partial: bool


def _lineup_ownership_is_partial(user: Any) -> bool:
    lineup = getattr(getattr(user, "lineupobj", None), "lineup", None)
    if not lineup:
        return True
    return any(
        is_locked_slot(slot)
        or (slot.get("ownership") if isinstance(slot, Mapping) else getattr(slot, "ownership", None)) in (None, "")
        for slot in lineup
    )


def _compute_field_remaining(full_standings: list[dict[str, Any]], users: Iterable[Any]) -> FieldRemaining:
    """Return the contest-field mean and whether any entry is incomplete.

    Runs over the full, pre-truncation standings. A row is left out when its lineup
    could not be resolved, so it carries no remaining-ownership total. Included
    entries with hidden or unresolved slots also make the field incomplete.
    """
    is_partial = any(row["ownership_remaining_total_pct"] is None for row in full_standings) or any(
        _lineup_ownership_is_partial(user) for user in users
    )
    return FieldRemaining(pct=_compute_ownership_remaining_total(full_standings), is_partial=is_partial)


def _compute_vip_remaining_by_entry_key(full_standings: list[dict[str, Any]]) -> dict[str, float]:
    """Map entry key to ownership remaining for every VIP standings row.

    Built from the full, pre-truncation standings, so a VIP ranked below the
    standings limit still has a value.
    """
    return {
        str(row["entry_key"]): row["ownership_remaining_total_pct"]
        for row in full_standings
        if row["is_vip"] and row["entry_key"] not in (None, "") and row["ownership_remaining_total_pct"] is not None
    }


def _apply_truncation(
    full_standings: list[dict[str, Any]],
    standings_limit: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Cap standings to the limit and describe what was truncated."""
    total_before = len(full_standings)
    limit = standings_limit if standings_limit and standings_limit > 0 else None
    applied = bool(limit and total_before > limit)
    standings = full_standings[:limit] if applied and limit is not None else full_standings
    truncation = {
        "applied": applied,
        "limit": limit,
        "total_rows_before_truncation": total_before,
        "total_rows_after_truncation": len(standings),
    }
    return standings, truncation


def _assemble_source_bundle(
    *,
    sport_cls: type[Sport],
    resolved: _ResolvedContest,
    dk_id: Any,
    draft_group: Any,
    cash_line: dict[str, Any],
    vip_lineups: list[Any],
    players: list[dict[str, Any]],
    ownership_remaining_total: float | None,
    field_remaining: FieldRemaining,
    vip_remaining_by_entry_key: dict[str, float],
    vip_remaining_is_partial_by_entry_key: dict[str, bool],
    avg_salary_per_player_remaining: Any,
    non_cashing_user_count: Any,
    non_cashing_avg_pmr: Any,
    watchlist_entries: list[Any],
    top_remaining_players: list[Any],
    train_clusters: list[Any],
    standings: list[dict[str, Any]],
    truncation: dict[str, Any],
) -> dict[str, Any]:
    """Assemble the raw source-snapshot dict from already-computed pieces (pure)."""
    state = _normalize_contest_state(resolved.contest_state, resolved.contest_completed)
    return {
        "sport": sport_cls.name,
        "contest": {
            "contest_id": dk_id,
            "name": resolved.contest_name,
            "sport": sport_cls.name.lower(),
            "draft_group": draft_group,
            "start_time_utc": to_utc_iso(resolved.start_date),
            "is_primary": True,
            "contest_type": "classic",
            "state": state,
            **completed_at_field(_completed_at_for(resolved, state)),
            "entry_fee": resolved.entry_fee,
            "currency": "USD",
            "entries": resolved.max_entries,
            "max_entries": resolved.max_entries,
            "max_entries_per_user": resolved.max_entries_per_user,
            "prize_pool": resolved.prize_pool,
            "positions_paid": resolved.positions_paid,
        },
        "selection": {
            "selected_contest_id": dk_id,
            "reason": _build_selection_reason(
                mode=resolved.mode,
                sport=sport_cls.name,
                min_entry_fee=sport_cls.sheet_min_entry_fee,
                keyword=sport_cls.keyword,
                selected_from_candidate_count=len(resolved.candidate_rows),
                contest_id=int(dk_id) if resolved.mode == "explicit_id" else None,
            ),
        },
        "candidates": _summarize_candidates(resolved.candidate_rows, top_n=CANDIDATE_LIMIT),
        "cash_line": cash_line,
        "vip_lineups": vip_lineups,
        "players": players,
        "ownership": {
            "ownership_remaining_total_pct": ownership_remaining_total,
            "field_remaining_pct": field_remaining.pct,
            "field_remaining_is_partial": field_remaining.is_partial,
            "vip_remaining_by_entry_key": vip_remaining_by_entry_key,
            "vip_remaining_is_partial_by_entry_key": vip_remaining_is_partial_by_entry_key,
            "avg_salary_per_player_remaining": avg_salary_per_player_remaining,
            "non_cashing_user_count": non_cashing_user_count,
            "non_cashing_avg_pmr": non_cashing_avg_pmr,
            "watchlist_entries": watchlist_entries,
            "non_cashing_top_remaining_players": top_remaining_players,
            "top_remaining_players": top_remaining_players,
        },
        "train_clusters": train_clusters,
        "standings": standings,
        "truncation": truncation,
    }


def _build_source_metrics(
    results: Any,
    *,
    leaderboard_payout_by_entry: dict[str, int],
    vip_lookup: set[str],
    vip_points_by_entry: dict[str, float | None],
    matchups: dict[str, str | None],
    scorecard_facts: dict[str, dict[str, Any]],
    standings_limit: int,
) -> dict[str, Any]:
    full_standings = sections.build_standings_rows(
        results,
        leaderboard_payout_by_entry=leaderboard_payout_by_entry,
        vip_lookup=vip_lookup,
        vip_points_by_entry=vip_points_by_entry,
    )
    standings, truncation = _apply_truncation(full_standings, standings_limit)
    vip_remaining_by_entry_key = _compute_vip_remaining_by_entry_key(full_standings)
    return {
        "players": sections.build_players(results, matchups=matchups, scorecard_facts=scorecard_facts),
        "ownership_remaining_total": _compute_ownership_remaining_total(full_standings),
        "field_remaining": _compute_field_remaining(full_standings, results.users),
        "vip_remaining_by_entry_key": vip_remaining_by_entry_key,
        "vip_remaining_is_partial_by_entry_key": {
            str(user.player_id): _lineup_ownership_is_partial(user)
            for user in results.users
            if str(user.player_id) in vip_remaining_by_entry_key
        },
        "avg_salary_per_player_remaining": average_remaining_salary(results.users),
        "top_remaining_players": sections.build_top_remaining_players(results),
        "watchlist_entries": sections.build_watchlist(full_standings),
        "standings": standings,
        "truncation": truncation,
        "cash_line": sections.build_cash_line(results, full_standings),
        "train_clusters": sections.build_train_clusters(results),
    }
