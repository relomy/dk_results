"""Build snapshot v3 sport payloads from raw and derived bundles."""

from __future__ import annotations

from typing import Any

from dk_results.services.snapshot_v3.derive import bundle_has_game_status


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


def _cash_line_type(cash_line: dict[str, Any]) -> str:
    raw_cutoff_type = str(cash_line.get("cutoff_type") or "").strip().lower()
    if raw_cutoff_type in {"positions_paid", "rank"}:
        return "rank"
    return "points" if raw_cutoff_type == "points" else "unknown"


def _cash_line_metric(cash_line: dict[str, Any]) -> dict[str, Any] | None:
    cutoff_type = _cash_line_type(cash_line)
    # A cutoff the collector could not determine is omitted, never null.
    cutoffs = {
        key: value
        for key, value in (("rank_cutoff", cash_line.get("rank")), ("points_cutoff", cash_line.get("points")))
        if value is not None
    }
    if not cutoffs or (cutoff_type != "unknown" and f"{cutoff_type}_cutoff" not in cutoffs):
        return None
    return {"cutoff_type": cutoff_type, **cutoffs}


def _build_contest(raw_bundle: dict[str, Any], derived: dict[str, Any], generated_at: str) -> dict[str, Any]:
    raw_contest = dict(raw_bundle.get("contest") or {})
    sport = str(raw_contest.get("sport") or raw_bundle.get("sport") or "").lower()
    contest_id = str(raw_contest.get("contest_id") or raw_bundle.get("selected_contest_id") or "")
    contest = _build_contest_fields(raw_bundle, raw_contest, sport, contest_id)
    _add_ownership_watchlist(contest, raw_bundle)
    _add_live_metrics(contest, raw_bundle, derived, generated_at)
    _add_derived_metrics(contest, derived, generated_at)
    return contest


def _build_contest_fields(
    raw_bundle: dict[str, Any], raw_contest: dict[str, Any], sport: str, contest_id: str
) -> dict[str, Any]:
    contest_key = f"{sport}:{contest_id}" if sport and contest_id else None
    fields = _base_contest_fields(raw_bundle, raw_contest, sport, contest_id, contest_key)
    fields.update(
        {
            "entry_fee_cents": _money_to_cents(raw_contest.get("entry_fee_cents") or raw_contest.get("entry_fee")),
            "prize_pool_cents": _money_to_cents(raw_contest.get("prize_pool_cents") or raw_contest.get("prize_pool")),
        }
    )
    return fields


def _base_contest_fields(
    raw_bundle: dict[str, Any],
    raw_contest: dict[str, Any],
    sport: str,
    contest_id: str,
    contest_key: str | None,
) -> dict[str, Any]:
    return {
        "contest_id": contest_id,
        "contest_key": contest_key,
        "name": raw_contest.get("name"),
        "sport": sport,
        "contest_type": raw_contest.get("contest_type") or "classic",
        "start_time": raw_contest.get("start_time") or raw_contest.get("start_time_utc"),
        "state": raw_contest.get("state"),
        "currency": raw_contest.get("currency") or "USD",
        "max_entries": raw_contest.get("max_entries") or raw_contest.get("entries"),
        "max_entries_per_user": raw_contest.get("max_entries_per_user"),
        "standings": _build_standings(raw_bundle),
        "vip_lineups": list(raw_bundle.get("vip_lineups") or []),
        "train_clusters": list(raw_bundle.get("train_clusters") or []),
    }


def _build_standings(raw_bundle: dict[str, Any]) -> list[dict[str, Any]]:
    has_game_status = bundle_has_game_status(raw_bundle)
    return [
        {
            key: value
            for key, value in row.items()
            if key != "ownership_remaining_total_pct" or (has_game_status and value is not None)
        }
        for row in list(raw_bundle.get("standings") or [])
    ]


def _add_ownership_watchlist(contest: dict[str, Any], raw_bundle: dict[str, Any]) -> None:
    if not bundle_has_game_status(raw_bundle):
        return
    watchlist = _build_ownership_watchlist(raw_bundle)
    if watchlist is not None:
        contest["ownership_watchlist"] = watchlist


def _build_ownership_watchlist(raw_bundle: dict[str, Any]) -> dict[str, Any] | None:
    ownership = dict(raw_bundle.get("ownership") or {})
    watchlist_entries = list(ownership.get("watchlist_entries") or [])
    ownership_watchlist: dict[str, Any] = {
        "entries": watchlist_entries,
    }
    total_pct = ownership.get("ownership_remaining_total_pct")
    if total_pct is not None:
        ownership_watchlist["ownership_remaining_total_pct"] = total_pct
    if ownership_watchlist["entries"] or "ownership_remaining_total_pct" in ownership_watchlist:
        return ownership_watchlist
    return None


def _add_live_metrics(
    contest: dict[str, Any], raw_bundle: dict[str, Any], derived: dict[str, Any], generated_at: str
) -> None:
    live_metrics: dict[str, Any] = {}
    cash_line_metric = _cash_line_metric(dict(raw_bundle.get("cash_line") or {}))
    if cash_line_metric is not None:
        live_metrics["cash_line"] = cash_line_metric

    avg_salary_remaining = derived.get("avg_salary_per_player_remaining")
    if isinstance(avg_salary_remaining, (int, float)):
        live_metrics["avg_salary_per_player_remaining"] = float(avg_salary_remaining)

    if live_metrics:
        live_metrics["updated_at"] = generated_at
        contest["live_metrics"] = live_metrics


# Derived metric sections, each with the key that must be non-empty for it to be
# emitted (None: the section itself must be non-empty).
_DERIVED_METRIC_GATES: dict[str, str | None] = {
    "distance_to_cash": "per_vip",
    "non_cashing": None,
    "ownership_summary": "per_vip",
    "threat": None,
}


def _is_emittable_metric(value: Any, required_key: str | None) -> bool:
    if not isinstance(value, dict) or not value:
        return False
    return required_key is None or bool(value.get(required_key))


def _add_derived_metrics(contest: dict[str, Any], derived: dict[str, Any], generated_at: str) -> None:
    metrics: dict[str, Any] = {
        name: derived[name]
        for name, required_key in _DERIVED_METRIC_GATES.items()
        if _is_emittable_metric(derived.get(name), required_key)
    }
    if metrics:
        metrics["updated_at"] = generated_at
        contest["metrics"] = metrics


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
