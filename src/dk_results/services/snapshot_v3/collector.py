"""Raw single-contest collector for snapshot v3."""

from __future__ import annotations

from typing import Any

from dk_results.services.snapshot_exporter import DEFAULT_STANDINGS_LIMIT, collect_snapshot_data


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
    selected_entry_keys = {
        str(row.get("entry_key"))
        for row in standings
        if isinstance(row, dict) and row.get("entry_key") not in (None, "")
    }

    vip_lineups: list[dict[str, Any]] = []
    for row in list(raw.get("vip_lineups") or []):
        if not isinstance(row, dict):
            continue
        entry_key = row.get("entry_key")
        if entry_key in (None, ""):
            continue
        if str(entry_key) in selected_entry_keys:
            vip_lineups.append(row)

    train_clusters: list[dict[str, Any]] = []
    for cluster in list(raw.get("train_clusters") or []):
        if not isinstance(cluster, dict):
            continue
        kept_entry_keys = [
            str(entry_key)
            for entry_key in list(cluster.get("entry_keys") or [])
            if entry_key not in (None, "") and str(entry_key) in selected_entry_keys
        ]
        if not kept_entry_keys:
            continue
        cluster_copy = dict(cluster)
        cluster_copy["entry_keys"] = kept_entry_keys
        train_clusters.append(cluster_copy)

    selection = dict(raw.get("selection") or {})
    return {
        "sport": raw.get("sport"),
        "contest": dict(raw.get("contest") or {}),
        "selected_contest_id": selection.get("selected_contest_id"),
        "selection_reason": selection.get("reason"),
        "candidates": list(raw.get("candidates") or []),
        "cash_line": dict(raw.get("cash_line") or {}),
        "players": list(raw.get("players") or []),
        "ownership": dict(raw.get("ownership") or {}),
        "standings": standings,
        "vip_lineups": vip_lineups,
        "train_clusters": train_clusters,
        "truncation": dict(raw.get("truncation") or {}),
        "metadata": dict(raw.get("metadata") or {}),
    }
