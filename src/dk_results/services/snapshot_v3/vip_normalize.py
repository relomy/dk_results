"""VIP lineup and player-key normalization of the collected source bundle (pure).

Gives players, VIP lineup slots and top-remaining rows a ``player_key``: their own,
one backfilled from a name that maps to exactly one key, or a composite key.
"""

from __future__ import annotations

from typing import Any

from dk_results.services.snapshot_v3.normalize import (
    is_live_from_slot,
    is_locked_snapshot_slot,
    normalize_name,
    resolve_lineup_slots,
    slug,
    to_float,
    to_int,
)


def _derive_composite_player_key(sport: str, row: dict[str, Any]) -> str | None:
    name_slug = slug(row.get("name") or row.get("player_name"))
    if not name_slug:
        return None
    team_slug = slug(row.get("team") or row.get("team_abbv")) or "na"
    pos_slug = slug(row.get("position") or row.get("pos")) or "na"
    salary_num = to_float(row.get("salary"))
    salary_part = str(int(round(salary_num))) if salary_num is not None else "na"
    return f"{sport.lower()}:{name_slug}:{team_slug}:{salary_part}:{pos_slug}"


def _trimmed(name: Any) -> Any:
    """The one place a player name loses its leading/trailing whitespace; non-strings pass through."""
    return name.strip() if isinstance(name, str) else name


def _with_trimmed_name(row: dict[str, Any], field: str) -> dict[str, Any]:
    """Copy ``row`` with its string name under ``field`` trimmed."""
    mapped = dict(row)
    if field in mapped:
        mapped[field] = _trimmed(mapped[field])
    return mapped


def _normalize_players(
    raw_players: list[Any],
    sport: str,
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    normalized_players: list[dict[str, Any]] = []
    keys_by_name: dict[str, set[str]] = {}

    for row in raw_players:
        if not isinstance(row, dict):
            continue
        mapped = _with_trimmed_name(row, "name")
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
    standings_entry_key_by_name = _unique_standings_entry_keys(standings)

    normalized_rows: list[dict[str, Any]] = []
    for row in raw_vip_lineups:
        normalized = _normalize_vip_lineup_row(row, sport, standings_entry_key_by_name, unique_name_to_player_key)
        if normalized:
            normalized_rows.append(normalized)

    # The fetcher returns lineups in worker-thread completion order; emit a stable order instead.
    return sorted(normalized_rows, key=_vip_lineup_order)


def _vip_lineup_order(row: dict[str, Any]) -> tuple[bool, int, bool, str, str]:
    """Rank ascending, then ``vip_entry_key``, then ``display_name``; a missing rank or key sorts last."""
    rank, vip_entry_key = row.get("rank"), row.get("vip_entry_key")
    return (rank is None, rank or 0, vip_entry_key is None, vip_entry_key or "", row.get("display_name", ""))


def _unique_standings_entry_keys(standings: list[dict[str, Any]]) -> dict[str, str]:
    keys_by_name: dict[str, set[str]] = {}
    for row in standings:
        if not isinstance(row, dict):
            continue
        username, entry_key = row.get("username"), row.get("entry_key")
        if username not in (None, "") and entry_key not in (None, ""):
            keys_by_name.setdefault(str(username).strip().lower(), set()).add(str(entry_key))
    return {name: next(iter(keys)) for name, keys in keys_by_name.items() if len(keys) == 1}


def _normalize_vip_lineup_row(
    row: Any,
    sport: str,
    standings_entry_keys: dict[str, str],
    unique_name_to_player_key: dict[str, str],
) -> dict[str, Any]:
    if not isinstance(row, dict):
        return {}
    display_name = row.get("display_name") or row.get("user") or row.get("username")
    entry_key = row.get("entry_key")
    if entry_key in (None, "") and display_name not in (None, ""):
        entry_key = standings_entry_keys.get(str(display_name).strip().lower())
    vip_entry_key = row.get("vip_entry_key") if row.get("vip_entry_key") not in (None, "") else entry_key
    normalized = _normalize_vip_identity(display_name, entry_key, vip_entry_key)
    normalized.update(_normalize_vip_figures(row))
    players_live = _normalize_vip_players(row, sport, unique_name_to_player_key)
    if players_live:
        normalized["players_live"] = players_live
    return normalized


def _normalize_vip_figures(row: dict[str, Any]) -> dict[str, Any]:
    """Coerce fetched VIP rank/points/PMR to numbers; omit any that do not parse."""
    figures = {
        "rank": to_int(row.get("rank")),
        "points": to_float(row.get("pts")),
        "pmr": to_float(row.get("pmr")),
    }
    return {key: value for key, value in figures.items() if value is not None}


def _normalize_vip_players(
    row: dict[str, Any], sport: str, unique_name_to_player_key: dict[str, str]
) -> list[dict[str, Any]]:
    players_live: list[dict[str, Any]] = []
    for slot in resolve_lineup_slots(row) or []:
        normalized = _normalize_vip_player_slot(slot, sport, unique_name_to_player_key)
        if normalized:
            players_live.append(normalized)
    return players_live


def _normalize_vip_identity(display_name: Any, entry_key: Any, vip_entry_key: Any) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for key, value in (
        ("display_name", display_name),
        ("entry_key", entry_key),
        ("vip_entry_key", vip_entry_key),
    ):
        if value not in (None, ""):
            normalized[key] = str(value)
    return normalized


def _slot_player_name(slot: dict[str, Any]) -> str:
    return str(_trimmed(slot.get("player_name") or slot.get("name") or ""))


def _normalize_vip_player_slot(
    slot: Any, sport: str, unique_name_to_player_key: dict[str, str]
) -> dict[str, Any] | None:
    if not isinstance(slot, dict):
        return None
    player_name = _slot_player_name(slot)
    if not player_name:
        return None
    roster_slot = slot.get("slot") or slot.get("pos")
    live_slot: dict[str, Any] = {
        "slot": str(roster_slot or ""),
        "player_name": player_name,
    }
    if is_locked_snapshot_slot(slot):
        live_slot["player_name"] = "LOCKED 🔒"
        live_slot["is_locked"] = True
        return live_slot

    return _normalize_revealed_vip_slot(live_slot, slot, sport, unique_name_to_player_key, player_name)


def _normalize_revealed_vip_slot(
    live_slot: dict[str, Any],
    slot: dict[str, Any],
    sport: str,
    unique_name_to_player_key: dict[str, str],
    player_name: Any,
) -> dict[str, Any]:
    player_key = slot.get("player_key")
    if player_key in (None, ""):
        player_key = unique_name_to_player_key.get(normalize_name(player_name))
    if player_key in (None, ""):
        player_key = _derive_composite_player_key(sport, {**slot, "player_name": player_name})
    if player_key not in (None, ""):
        live_slot["player_key"] = str(player_key)
    salary = to_float(slot.get("salary"))
    if salary is not None:
        live_slot["salary"] = int(round(salary))
    live_slot["is_live"] = is_live_from_slot(slot)
    return live_slot


def _collect_slot_names_and_keys(slots: list[Any], keys_by_name: dict[str, set[str]]) -> None:
    for slot in slots:
        _collect_slot_name_and_key(slot, keys_by_name)


def _collect_slot_name_and_key(slot: Any, keys_by_name: dict[str, set[str]]) -> None:
    if not isinstance(slot, dict) or is_locked_snapshot_slot(slot):
        return
    player_name = slot.get("player_name") or slot.get("name")
    player_key = slot.get("player_key")
    if player_name in (None, "") or player_key in (None, ""):
        return
    keys_by_name.setdefault(normalize_name(player_name), set()).add(str(player_key))


def _build_unique_name_to_player_key_from_vip_lineups(vip_lineups: list[dict[str, Any]]) -> dict[str, str]:
    keys_by_name: dict[str, set[str]] = {}

    for vip_row in vip_lineups:
        if not isinstance(vip_row, dict):
            continue
        slots = vip_row.get("players_live")
        if not isinstance(slots, list):
            continue
        _collect_slot_names_and_keys(slots, keys_by_name)

    return {name_key: next(iter(keys)) for name_key, keys in keys_by_name.items() if len(keys) == 1}


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
        mapped = _with_trimmed_name(row, "player_name")
        player_name = mapped.get("player_name")
        player_key = mapped.get("player_key")
        if player_key in (None, "") and player_name not in (None, ""):
            player_key = unique_name_to_player_key.get(normalize_name(player_name))
        if player_key not in (None, ""):
            mapped["player_key"] = str(player_key)
        normalized_rows.append(mapped)
    return normalized_rows


def _normalize_ownership_top_lists(
    ownership: dict[str, Any], unique_name_to_player_key: dict[str, str]
) -> dict[str, Any]:
    normalized = dict(ownership)
    for field in ("non_cashing_top_remaining_players", "top_remaining_players"):
        rows = normalized.get(field)
        if isinstance(rows, list):
            normalized[field] = _normalize_top_remaining_players(rows, unique_name_to_player_key)
    return normalized
