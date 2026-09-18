"""Pure derive helpers for snapshot v3 metrics."""

from __future__ import annotations

from typing import Any, Iterable

from dk_results.services.snapshot_v3.normalize import is_live_from_slot, resolve_lineup_slots, to_float, to_int


def _sorted_vip_rows(vip_lineups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        vip_lineups,
        key=lambda row: (
            str(row.get("vip_entry_key") or ""),
            str(row.get("entry_key") or ""),
            str(row.get("display_name") or ""),
        ),
    )


def _build_distance_to_cash_entry(
    row: dict[str, Any], cutoff_points: float | None, rank_cutoff: int | None
) -> dict[str, Any] | None:
    current_points = to_float(row.get("pts"))
    if current_points is None or cutoff_points is None:
        return None

    entry: dict[str, Any] = {
        "vip_entry_key": row.get("vip_entry_key"),
        "entry_key": row.get("entry_key"),
        "display_name": row.get("display_name"),
        "points_delta": round(current_points - cutoff_points, 2),
    }

    current_rank = to_int(row.get("rank"))
    if rank_cutoff is not None and current_rank is not None:
        entry["rank_delta"] = rank_cutoff - current_rank

    return entry


def derive_distance_to_cash(raw_bundle: dict[str, Any]) -> dict[str, Any] | None:
    cash_line = dict(raw_bundle.get("cash_line") or {})
    vip_lineups = [row for row in list(raw_bundle.get("vip_lineups") or []) if isinstance(row, dict)]

    cutoff_points = to_float(cash_line.get("points"))
    rank_cutoff = to_int(cash_line.get("rank"))

    per_vip = [
        entry
        for row in _sorted_vip_rows(vip_lineups)
        if (entry := _build_distance_to_cash_entry(row, cutoff_points, rank_cutoff)) is not None
    ]

    if not per_vip:
        return None

    metric: dict[str, Any] = {"per_vip": per_vip}
    if cutoff_points is not None:
        metric["cutoff_points"] = cutoff_points
    return metric


def _iter_vip_lineup_player_keys(vip_lineups: list[dict[str, Any]]) -> Iterable[str]:
    for lineup_row in vip_lineups:
        slots = resolve_lineup_slots(lineup_row)
        if slots is None:
            continue
        seen_in_lineup: set[str] = set()
        for slot in slots:
            if not isinstance(slot, dict):
                continue
            player_key = slot.get("player_key")
            if player_key in (None, ""):
                continue
            normalized_key = str(player_key)
            if normalized_key in seen_in_lineup:
                continue
            seen_in_lineup.add(normalized_key)
            yield normalized_key


def _resolve_threat_top_source(ownership: dict[str, Any]) -> list[Any] | None:
    for key in ("non_cashing_top_remaining_players", "top_remaining_players"):
        top_source = ownership.get(key)
        if isinstance(top_source, list):
            return top_source
    return None


def _build_threat_row(row: Any, vip_counts: dict[str, int], seen_player_keys: set[str]) -> dict[str, Any] | None:
    if not isinstance(row, dict):
        return None
    player_key = row.get("player_key")
    player_name = row.get("player_name")
    if player_name in (None, "") or player_key in (None, ""):
        return None

    normalized_key = str(player_key)
    if normalized_key in seen_player_keys:
        raise ValueError(f"duplicate player_key in threat rows: {normalized_key}")
    seen_player_keys.add(normalized_key)

    ownership_remaining_pct = to_float(row.get("ownership_remaining_pct"))
    threat_row: dict[str, Any] = {
        "player_key": normalized_key,
        "player_name": str(player_name),
        "vip_count": int(vip_counts.get(normalized_key, 0)),
    }
    if ownership_remaining_pct is not None:
        threat_row["ownership_remaining_pct"] = round(ownership_remaining_pct, 2)
    return threat_row


def _count_vip_lineup_players(vip_lineups: list[dict[str, Any]]) -> dict[str, int]:
    vip_counts: dict[str, int] = {}
    for player_key in _iter_vip_lineup_player_keys(vip_lineups):
        vip_counts[player_key] = vip_counts.get(player_key, 0) + 1
    return vip_counts


def _threat_sort_key(row: dict[str, Any]) -> tuple[bool, float, str]:
    return (
        row.get("ownership_remaining_pct") is None,
        -(row.get("ownership_remaining_pct") or 0.0),
        str(row.get("player_key") or ""),
    )


def derive_threat(raw_bundle: dict[str, Any]) -> dict[str, Any] | None:
    ownership = dict(raw_bundle.get("ownership") or {})
    vip_lineups = [row for row in list(raw_bundle.get("vip_lineups") or []) if isinstance(row, dict)]

    top_source = _resolve_threat_top_source(ownership)
    if top_source is None:
        return None

    vip_counts = _count_vip_lineup_players(vip_lineups)

    seen_player_keys: set[str] = set()
    top_swing_players = [
        threat_row
        for row in top_source
        if (threat_row := _build_threat_row(row, vip_counts, seen_player_keys)) is not None
    ]

    if not top_swing_players:
        return None

    top_swing_players.sort(key=_threat_sort_key)

    return {"top_swing_players": top_swing_players}


def _collect_live_slot_salaries(lineup_row: dict[str, Any]) -> list[float]:
    slots = resolve_lineup_slots(lineup_row)
    if slots is None:
        return []
    salaries: list[float] = []
    for slot in slots:
        if not isinstance(slot, dict):
            continue
        if not is_live_from_slot(slot):
            continue
        salary = to_float(slot.get("salary"))
        if salary is None:
            continue
        salaries.append(salary)
    return salaries


def derive_avg_salary_per_player_remaining(raw_bundle: dict[str, Any]) -> float | None:
    vip_lineups = [row for row in list(raw_bundle.get("vip_lineups") or []) if isinstance(row, dict)]

    live_slot_salaries: list[float] = []
    for lineup_row in vip_lineups:
        live_slot_salaries.extend(_collect_live_slot_salaries(lineup_row))

    if not live_slot_salaries:
        return None

    return round(sum(live_slot_salaries) / len(live_slot_salaries), 2)
