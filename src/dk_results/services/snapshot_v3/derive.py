"""Pure derive helpers for snapshot v3 metrics."""

from __future__ import annotations

from typing import Any, Iterable


def _to_float(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip().replace("$", "").replace(",", "")
        if not text:
            return None
        try:
            return float(text)
        except ValueError:
            return None
    return None


def _to_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if value.is_integer():
            return int(value)
        return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return int(text)
        except ValueError:
            return None
    return None


def _sorted_vip_rows(vip_lineups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        vip_lineups,
        key=lambda row: (
            str(row.get("vip_entry_key") or ""),
            str(row.get("entry_key") or ""),
            str(row.get("display_name") or ""),
        ),
    )


def derive_distance_to_cash(raw_bundle: dict[str, Any]) -> dict[str, Any] | None:
    cash_line = dict(raw_bundle.get("cash_line") or {})
    vip_lineups = [row for row in list(raw_bundle.get("vip_lineups") or []) if isinstance(row, dict)]

    cutoff_points = _to_float(cash_line.get("points"))
    rank_cutoff = _to_int(cash_line.get("rank"))

    per_vip: list[dict[str, Any]] = []
    for row in _sorted_vip_rows(vip_lineups):
        current_points = _to_float(row.get("pts"))
        if current_points is None or cutoff_points is None:
            continue

        entry = {
            "vip_entry_key": row.get("vip_entry_key"),
            "entry_key": row.get("entry_key"),
            "display_name": row.get("display_name"),
            "points_delta": round(current_points - cutoff_points, 2),
        }

        current_rank = _to_int(row.get("rank"))
        if rank_cutoff is not None and current_rank is not None:
            entry["rank_delta"] = rank_cutoff - current_rank

        per_vip.append(entry)

    if not per_vip:
        return None

    metric: dict[str, Any] = {"per_vip": per_vip}
    if cutoff_points is not None:
        metric["cutoff_points"] = cutoff_points
    return metric


def _iter_vip_lineup_player_keys(vip_lineups: list[dict[str, Any]]) -> Iterable[str]:
    for lineup_row in vip_lineups:
        slots = lineup_row.get("players_live")
        if not isinstance(slots, list):
            slots = lineup_row.get("lineup")
        if not isinstance(slots, list):
            slots = lineup_row.get("players")
        if not isinstance(slots, list):
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


def derive_threat(raw_bundle: dict[str, Any]) -> dict[str, Any] | None:
    ownership = dict(raw_bundle.get("ownership") or {})
    vip_lineups = [row for row in list(raw_bundle.get("vip_lineups") or []) if isinstance(row, dict)]

    top_source = ownership.get("non_cashing_top_remaining_players")
    if not isinstance(top_source, list):
        top_source = ownership.get("top_remaining_players")
    if not isinstance(top_source, list):
        return None

    vip_counts: dict[str, int] = {}
    for player_key in _iter_vip_lineup_player_keys(vip_lineups):
        vip_counts[player_key] = vip_counts.get(player_key, 0) + 1

    top_swing_players: list[dict[str, Any]] = []
    seen_player_keys: set[str] = set()

    for row in top_source:
        if not isinstance(row, dict):
            continue
        player_key = row.get("player_key")
        player_name = row.get("player_name")
        if player_name in (None, ""):
            continue
        if player_key in (None, ""):
            continue

        ownership_remaining_pct = _to_float(row.get("ownership_remaining_pct"))

        normalized_key = str(player_key)
        if normalized_key in seen_player_keys:
            raise ValueError(f"duplicate player_key in threat rows: {normalized_key}")
        seen_player_keys.add(normalized_key)

        threat_row: dict[str, Any] = {
            "player_key": normalized_key,
            "player_name": str(player_name),
            "vip_count": int(vip_counts.get(normalized_key, 0)),
        }
        if ownership_remaining_pct is not None:
            threat_row["ownership_remaining_pct"] = round(ownership_remaining_pct, 2)
        top_swing_players.append(threat_row)

    if not top_swing_players:
        return None

    top_swing_players.sort(
        key=lambda row: (
            row.get("ownership_remaining_pct") is None,
            -(row.get("ownership_remaining_pct") or 0.0),
            str(row.get("player_key") or ""),
        )
    )

    return {"top_swing_players": top_swing_players}


def derive_avg_salary_per_player_remaining(raw_bundle: dict[str, Any]) -> float | None:
    vip_lineups = [row for row in list(raw_bundle.get("vip_lineups") or []) if isinstance(row, dict)]

    live_slot_salaries: list[float] = []
    for lineup_row in vip_lineups:
        slots = lineup_row.get("players_live")
        if not isinstance(slots, list):
            slots = lineup_row.get("lineup")
        if not isinstance(slots, list):
            slots = lineup_row.get("players")
        if not isinstance(slots, list):
            continue
        for slot in slots:
            if not isinstance(slot, dict):
                continue
            is_live = slot.get("is_live")
            if not isinstance(is_live, bool):
                time_remaining = _to_float(
                    slot.get("time_remaining_minutes")
                    if slot.get("time_remaining_minutes") is not None
                    else slot.get("timeStatus")
                )
                if time_remaining is not None:
                    is_live = time_remaining > 0
                else:
                    text_candidates = [
                        slot.get("timeStatus"),
                        slot.get("time_remaining_display"),
                        slot.get("timeRemaining"),
                        slot.get("game_status"),
                        slot.get("status"),
                    ]
                    live_markers = ("in progress", "live", "q1", "q2", "q3", "q4", "ot", "thru", "hole")
                    final_markers = ("final", "complete", "completed", "locked", "postponed", "canceled", "cancelled")
                    is_live = False
                    for raw_text in text_candidates:
                        status_text = str(raw_text or "").strip().lower()
                        if not status_text or status_text in {"-", "--"}:
                            continue
                        if any(marker in status_text for marker in final_markers):
                            is_live = False
                            break
                        if any(marker in status_text for marker in live_markers):
                            is_live = True
                            break
                        if ":" in status_text:
                            is_live = True
                            break
            if is_live is not True:
                continue
            salary = _to_float(slot.get("salary"))
            if salary is None:
                continue
            live_slot_salaries.append(salary)

    if not live_slot_salaries:
        return None

    return round(sum(live_slot_salaries) / len(live_slot_salaries), 2)
