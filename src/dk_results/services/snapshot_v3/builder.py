"""Build snapshot v3 sport payloads from raw and derived bundles."""

from __future__ import annotations

from typing import Any


def _money_to_cents(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(round(float(value) * 100))
    if isinstance(value, str):
        text = value.strip().replace("$", "").replace(",", "")
        if not text:
            return None
        try:
            return int(round(float(text) * 100))
        except ValueError:
            return None
    return None


def _cash_line_metric(cash_line: dict[str, Any]) -> dict[str, Any] | None:
    rank_cutoff = cash_line.get("rank")
    points_cutoff = cash_line.get("points")
    raw_cutoff_type = str(cash_line.get("cutoff_type") or "").strip().lower()
    if raw_cutoff_type in {"positions_paid", "rank"}:
        cutoff_type = "rank"
    elif raw_cutoff_type == "points":
        cutoff_type = "points"
    else:
        cutoff_type = "unknown"

    metric: dict[str, Any] = {
        "cutoff_type": cutoff_type,
        "rank_cutoff": rank_cutoff,
        "points_cutoff": points_cutoff,
    }
    if metric["rank_cutoff"] is None and metric["points_cutoff"] is None and cutoff_type == "unknown":
        return None
    return metric


def _build_contest(raw_bundle: dict[str, Any], derived: dict[str, Any], generated_at: str) -> dict[str, Any]:
    raw_contest = dict(raw_bundle.get("contest") or {})
    sport = str(raw_contest.get("sport") or raw_bundle.get("sport") or "").lower()
    contest_id = str(raw_contest.get("contest_id") or raw_bundle.get("selected_contest_id") or "")
    contest_key = f"{sport}:{contest_id}" if sport and contest_id else None

    contest: dict[str, Any] = {
        "contest_id": contest_id,
        "contest_key": contest_key,
        "name": raw_contest.get("name"),
        "sport": sport,
        "contest_type": raw_contest.get("contest_type") or "classic",
        "start_time": raw_contest.get("start_time") or raw_contest.get("start_time_utc"),
        "state": raw_contest.get("state"),
        "entry_fee_cents": _money_to_cents(raw_contest.get("entry_fee_cents") or raw_contest.get("entry_fee")),
        "prize_pool_cents": _money_to_cents(raw_contest.get("prize_pool_cents") or raw_contest.get("prize_pool")),
        "currency": raw_contest.get("currency") or "USD",
        "max_entries": raw_contest.get("max_entries") or raw_contest.get("entries"),
        "max_entries_per_user": raw_contest.get("max_entries_per_user"),
        "standings": list(raw_bundle.get("standings") or []),
        "vip_lineups": list(raw_bundle.get("vip_lineups") or []),
        "train_clusters": list(raw_bundle.get("train_clusters") or []),
    }

    ownership = dict(raw_bundle.get("ownership") or {})
    watchlist_entries = list(ownership.get("watchlist_entries") or [])
    ownership_watchlist: dict[str, Any] = {
        "entries": watchlist_entries,
    }
    total_pct = ownership.get("ownership_remaining_total_pct")
    if total_pct is not None:
        ownership_watchlist["ownership_remaining_total_pct"] = total_pct
    if ownership_watchlist["entries"] or "ownership_remaining_total_pct" in ownership_watchlist:
        contest["ownership_watchlist"] = ownership_watchlist

    live_metrics: dict[str, Any] = {}
    cash_line_metric = _cash_line_metric(dict(raw_bundle.get("cash_line") or {}))
    if cash_line_metric is not None:
        live_metrics["cash_line"] = cash_line_metric

    avg_salary_remaining = derived.get("avg_salary_per_player_remaining")
    if isinstance(avg_salary_remaining, (int, float)):
        live_metrics["avg_salary_per_player_remaining"] = float(avg_salary_remaining)

    if live_metrics:
        contest["live_metrics"] = live_metrics

    metrics: dict[str, Any] = {}
    distance_to_cash = derived.get("distance_to_cash")
    if isinstance(distance_to_cash, dict) and distance_to_cash.get("per_vip"):
        metrics["distance_to_cash"] = distance_to_cash

    threat = derived.get("threat")
    if isinstance(threat, dict) and threat.get("top_swing_players"):
        metrics["threat"] = threat

    if metrics:
        metrics["updated_at"] = generated_at
        contest["metrics"] = metrics

    return contest


def build_sport_payload(raw_bundle: dict[str, Any], *, derived: dict[str, Any], generated_at: str) -> dict[str, Any]:
    contest = _build_contest(raw_bundle, derived, generated_at)
    contest_id = str(contest.get("contest_id") or "")
    contest_key = str(contest.get("contest_key") or "")

    return {
        "status": "ok",
        "updated_at": generated_at,
        "players": list(raw_bundle.get("players") or []),
        "primary_contest": {
            "contest_id": contest_id,
            "contest_key": contest_key,
            "selection_reason": raw_bundle.get("selection_reason"),
            "selected_at": generated_at,
        },
        "contests": [contest],
    }
