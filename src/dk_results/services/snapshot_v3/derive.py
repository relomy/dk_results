"""Pure derive helpers for snapshot v3 metrics."""

from __future__ import annotations

from typing import Any, Iterable

from dk_results.analytics.game_status import UNKNOWN, classify_game_status, is_locked_slot, sport_has_game_status
from dk_results.domain.contest_standings import NON_CASHING_TALLY_SPORTS
from dk_results.services.snapshot_v3.models.metrics import (
    FIELD_REMAINING_SCOPE,
    FIELD_REMAINING_SOURCE,
    LEVERAGE_SEMANTICS,
    OWNERSHIP_SUMMARY_SCOPE,
    OWNERSHIP_SUMMARY_SOURCE,
    TOP_REMAINING_PLAYERS_LIMIT,
)
from dk_results.services.snapshot_v3.normalize import resolve_lineup_slots, to_float, to_int


def _vip_lineup_rows(raw_bundle: dict[str, Any]) -> list[dict[str, Any]]:
    return [row for row in list(raw_bundle.get("vip_lineups") or []) if isinstance(row, dict)]


def _ownership(raw_bundle: dict[str, Any]) -> dict[str, Any]:
    return dict(raw_bundle.get("ownership") or {})


def _sorted_vip_rows(vip_lineups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        vip_lineups,
        key=lambda row: (
            str(row.get("vip_entry_key") or ""),
            str(row.get("entry_key") or ""),
            str(row.get("display_name") or ""),
        ),
    )


def _vip_identity(row: dict[str, Any]) -> dict[str, Any]:
    return {key: row[key] for key in ("vip_entry_key", "entry_key", "display_name") if row.get(key) not in (None, "")}


def _build_distance_to_cash_entry(
    row: dict[str, Any], cutoff_points: float | None, rank_cutoff: int | None
) -> dict[str, Any] | None:
    current_points = to_float(row.get("points"))
    if current_points is None or cutoff_points is None:
        return None

    entry = _vip_identity(row)
    entry["points_delta"] = round(current_points - cutoff_points, 2)

    current_rank = to_int(row.get("rank"))
    if rank_cutoff is not None and current_rank is not None:
        entry["rank_delta"] = rank_cutoff - current_rank

    return entry


def derive_distance_to_cash(raw_bundle: dict[str, Any]) -> dict[str, Any] | None:
    cash_line = dict(raw_bundle.get("cash_line") or {})
    vip_lineups = _vip_lineup_rows(raw_bundle)

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
        yield from _iter_lineup_player_keys(slots)


def _iter_lineup_player_keys(slots: list[Any]) -> Iterable[str]:
    seen_in_lineup: set[str] = set()
    for slot in slots:
        if not isinstance(slot, dict) or is_locked_slot(slot):
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


def _derive_top_swing_players(raw_bundle: dict[str, Any]) -> list[dict[str, Any]]:
    if not bundle_has_game_status(raw_bundle):
        return []
    ownership = _ownership(raw_bundle)
    vip_lineups = _vip_lineup_rows(raw_bundle)

    top_source = _resolve_threat_top_source(ownership)
    if top_source is None:
        return []

    vip_counts = _count_vip_lineup_players(vip_lineups)

    seen_player_keys: set[str] = set()
    top_swing_players = [
        threat_row
        for row in top_source
        if (threat_row := _build_threat_row(row, vip_counts, seen_player_keys)) is not None
    ]
    top_swing_players.sort(key=_threat_sort_key)
    return top_swing_players


def derive_threat(raw_bundle: dict[str, Any]) -> dict[str, Any] | None:
    """Combine top swing players, field remaining and VIP leverage; None when all are absent."""

    threat: dict[str, Any] = {}
    top_swing_players = _derive_top_swing_players(raw_bundle)
    if top_swing_players:
        threat["top_swing_players"] = top_swing_players
    field_remaining = derive_field_remaining(raw_bundle)
    if field_remaining is not None:
        threat.update(field_remaining)
        leverage = derive_vip_vs_field_leverage(raw_bundle, field_remaining["field_remaining_pct"])
        if leverage:
            threat["vip_vs_field_leverage"] = leverage
    return threat or None


def bundle_has_game_status(raw_bundle: dict[str, Any]) -> bool:
    """Return True when any player in the bundle's pool carries a Game status.

    False means the sport has no Game status (today: golf), so every
    "remaining" and "in play" metric must be omitted.
    """

    players = [row for row in list(raw_bundle.get("players") or []) if isinstance(row, dict)]
    return sport_has_game_status(row.get("game_status") for row in players)


def derive_field_remaining(raw_bundle: dict[str, Any]) -> dict[str, Any] | None:
    """Return the contest-field remaining threat fields, or None when they are omitted.

    The collector computes the mean over the full, pre-truncation standings.
    Omitted for a sport with no Game status, or when no row had a resolvable lineup.
    """

    ownership = _ownership(raw_bundle)
    field_remaining_pct = to_float(ownership.get("field_remaining_pct"))
    if field_remaining_pct is None or not bundle_has_game_status(raw_bundle):
        return None
    return {
        "leverage_semantics": LEVERAGE_SEMANTICS,
        "field_remaining_scope": FIELD_REMAINING_SCOPE,
        "field_remaining_source": FIELD_REMAINING_SOURCE,
        "field_remaining_pct": round(field_remaining_pct, 2),
        "field_remaining_is_partial": ownership.get("field_remaining_is_partial") is True,
    }


def _vip_remaining_by_entry(ownership: dict[str, Any]) -> dict[str, float]:
    raw = ownership.get("vip_remaining_by_entry_key")
    remaining_by_entry: dict[str, float] = {}
    for entry_key, value in (raw if isinstance(raw, dict) else {}).items():
        remaining = to_float(value)
        if remaining is not None:
            remaining_by_entry[str(entry_key)] = remaining
    return remaining_by_entry


def _build_leverage_row(
    vip_row: dict[str, Any],
    remaining_by_entry: dict[str, float],
    partial_by_entry: dict[str, Any],
    field_remaining_pct: float,
) -> dict[str, Any] | None:
    entry_key = vip_row.get("entry_key")
    if (
        entry_key in (None, "")
        or vip_row.get("vip_entry_key") in (None, "")
        or vip_row.get("display_name") in (None, "")
    ):
        return None
    vip_remaining = remaining_by_entry.get(str(entry_key))
    if vip_remaining is None:
        return None
    vip_remaining_pct = round(vip_remaining, 2)
    return {
        "vip_entry_key": vip_row["vip_entry_key"],
        "entry_key": entry_key,
        "display_name": vip_row["display_name"],
        "vip_remaining_pct": vip_remaining_pct,
        "field_remaining_pct": field_remaining_pct,
        "uniqueness_delta_pct": round(field_remaining_pct - vip_remaining_pct, 2),
        "is_partial": partial_by_entry.get(str(entry_key)) is True,
    }


def derive_vip_vs_field_leverage(raw_bundle: dict[str, Any], field_remaining_pct: float) -> list[dict[str, Any]]:
    """One row per tracked VIP matched to a standings row by entry key; unmatched VIPs are left out.

    The collector keys VIP remaining by entry key from the full, pre-truncation
    standings, so a VIP ranked below the standings limit is still matched.
    """

    vip_lineups = _vip_lineup_rows(raw_bundle)
    ownership = _ownership(raw_bundle)
    remaining_by_entry = _vip_remaining_by_entry(ownership)
    partial_by_entry = ownership.get("vip_remaining_is_partial_by_entry_key")
    if not isinstance(partial_by_entry, dict):
        partial_by_entry = {}
    return [
        row
        for vip_row in _sorted_vip_rows(vip_lineups)
        if (row := _build_leverage_row(vip_row, remaining_by_entry, partial_by_entry, field_remaining_pct)) is not None
    ]


def derive_avg_salary_per_player_remaining(raw_bundle: dict[str, Any]) -> float | None:
    """Return the collector's average salary remaining, or None when it is omitted."""

    value = to_float(_ownership(raw_bundle).get("avg_salary_per_player_remaining"))
    if value is None or not bundle_has_game_status(raw_bundle):
        return None
    return round(value, 2)


def _bundle_sport(raw_bundle: dict[str, Any]) -> str:
    return str(raw_bundle.get("sport") or dict(raw_bundle.get("contest") or {}).get("sport") or "").lower()


def _build_top_remaining_players(rows: Any) -> list[dict[str, Any]]:
    top_players: list[dict[str, Any]] = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict) or row.get("player_name") in (None, ""):
            continue
        ownership_remaining_pct = to_float(row.get("ownership_remaining_pct"))
        if ownership_remaining_pct is None:
            continue
        top_players.append(
            {"player_name": str(row["player_name"]), "ownership_remaining_pct": round(ownership_remaining_pct, 2)}
        )
    return top_players[:TOP_REMAINING_PLAYERS_LIMIT]


def _has_non_cashing_player_tally(raw_bundle: dict[str, Any]) -> bool:
    return bundle_has_game_status(raw_bundle) and _bundle_sport(raw_bundle) in {
        sport.lower() for sport in NON_CASHING_TALLY_SPORTS
    }


def derive_non_cashing(raw_bundle: dict[str, Any]) -> dict[str, Any] | None:
    ownership = _ownership(raw_bundle)
    users_not_cashing = to_int(ownership.get("non_cashing_user_count"))
    avg_pmr_remaining = to_float(ownership.get("non_cashing_avg_pmr"))
    if users_not_cashing is None or users_not_cashing <= 0 or avg_pmr_remaining is None:
        return None

    metric: dict[str, Any] = {
        "users_not_cashing": users_not_cashing,
        "avg_pmr_remaining": round(avg_pmr_remaining, 2),
    }
    if _has_non_cashing_player_tally(raw_bundle):
        metric["top_remaining_players"] = _build_top_remaining_players(_resolve_threat_top_source(ownership))
    return metric


def _player_rows_by_key(raw_bundle: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for row in list(raw_bundle.get("players") or []):
        if isinstance(row, dict) and row.get("player_key") not in (None, ""):
            rows.setdefault(str(row["player_key"]), row)
    return rows


def _slot_ownership(slot: Any, players: dict[str, dict[str, Any]]) -> tuple[float, bool, bool] | None:
    """Return (ownership, in_play, known_status) for a usable slot, else None."""

    if not isinstance(slot, dict) or is_locked_slot(slot):
        return None
    player = players.get(str(slot.get("player_key")))
    ownership = to_float(player.get("ownership_pct")) if player else None
    if player is None or ownership is None:
        return None
    status = classify_game_status(player.get("game_status"))
    return ownership, bool(status.in_play), status is not UNKNOWN


def _summarize_vip_ownership(
    row: dict[str, Any], slots: list[Any], players: dict[str, dict[str, Any]], has_game_status: bool
) -> dict[str, Any]:
    total = 0.0
    in_play = 0.0
    is_partial = False
    for slot in slots:
        usable = _slot_ownership(slot, players)
        if usable is None:
            is_partial = True
            continue
        ownership, slot_in_play, known_status = usable
        total += ownership
        in_play += ownership if slot_in_play else 0.0
        is_partial = is_partial or not known_status
    summary: dict[str, Any] = {
        key: row[key] for key in ("vip_entry_key", "entry_key", "display_name") if row.get(key) not in (None, "")
    }
    summary["total_ownership_pct"] = round(total, 2)
    if has_game_status:
        summary["ownership_in_play_pct"] = round(in_play, 2)
    summary["is_partial"] = is_partial
    return summary


def derive_ownership_summary(raw_bundle: dict[str, Any]) -> dict[str, Any] | None:
    """Per-VIP total ownership and ownership in play, looked up in ``players[]``.

    A slot is partial when locked, unmatched to a player (or one without
    ownership), or when its Game status is unknown, including golf-like pools.
    Omitted when no tracked VIP has a lineup.
    """

    players = _player_rows_by_key(raw_bundle)
    has_game_status = bundle_has_game_status(raw_bundle)
    vip_lineups = _vip_lineup_rows(raw_bundle)
    per_vip = [
        _summarize_vip_ownership(row, slots, players, has_game_status)
        for row in _sorted_vip_rows(vip_lineups)
        if row.get("vip_entry_key") not in (None, "") and (slots := resolve_lineup_slots(row))
    ]
    if not per_vip:
        return None
    return {"source": OWNERSHIP_SUMMARY_SOURCE, "scope": OWNERSHIP_SUMMARY_SCOPE, "per_vip": per_vip}
