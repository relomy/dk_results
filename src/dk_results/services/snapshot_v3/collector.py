"""Raw single-contest collector for snapshot v3."""

from __future__ import annotations

import re
from typing import Any

from dk_results.services.snapshot_exporter import DEFAULT_STANDINGS_LIMIT, collect_snapshot_data


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


def _normalize_name(value: Any) -> str:
    return str(value or "").strip().lower()


def _slug(value: Any) -> str:
    normalized = _normalize_name(value)
    if not normalized:
        return ""
    return re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")


def _derive_composite_player_key(sport: str, row: dict[str, Any]) -> str | None:
    name_slug = _slug(row.get("name") or row.get("player_name"))
    if not name_slug:
        return None
    team_slug = _slug(row.get("team") or row.get("team_abbv")) or "na"
    pos_slug = _slug(row.get("position") or row.get("pos")) or "na"
    salary_num = _to_float(row.get("salary"))
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

        name_key = _normalize_name(mapped.get("name") or mapped.get("player_name"))
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


def _is_live_from_slot(slot: dict[str, Any]) -> bool:
    raw_is_live = slot.get("is_live")
    if isinstance(raw_is_live, bool):
        return raw_is_live

    for key in ("time_remaining_minutes", "timeRemaining", "timeStatus", "time_remaining_display"):
        minutes = _to_float(slot.get(key))
        if minutes is not None:
            return minutes > 0

    text_candidates = [
        slot.get("timeStatus"),
        slot.get("time_remaining_display"),
        slot.get("timeRemaining"),
        slot.get("game_status"),
        slot.get("status"),
    ]
    live_markers = ("in progress", "live", "q1", "q2", "q3", "q4", "ot", "thru", "hole")
    final_markers = ("final", "complete", "completed", "locked", "postponed", "canceled", "cancelled")
    for raw_text in text_candidates:
        status_text = str(raw_text or "").strip().lower()
        if not status_text or status_text in {"-", "--"}:
            continue
        if any(marker in status_text for marker in final_markers):
            return False
        if any(marker in status_text for marker in live_markers):
            return True
        if ":" in status_text:
            return True
    return False


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
                player_key = unique_name_to_player_key.get(_normalize_name(player_name))
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
            salary = _to_float(slot.get("salary"))
            if salary is not None:
                live_slot["salary"] = int(round(salary))
            live_slot["is_live"] = _is_live_from_slot(slot)
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
            keys_by_name.setdefault(_normalize_name(player_name), set()).add(str(player_key))

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
            player_key = unique_name_to_player_key.get(_normalize_name(player_name))
        if player_key not in (None, ""):
            mapped["player_key"] = str(player_key)
        normalized_rows.append(mapped)
    return normalized_rows


def collect_raw_bundle(
    *,
    sport: str,
    contest_id: int | None = None,
    standings_limit: int = DEFAULT_STANDINGS_LIMIT,
) -> dict[str, Any]:
    raw = collect_snapshot_data(
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
