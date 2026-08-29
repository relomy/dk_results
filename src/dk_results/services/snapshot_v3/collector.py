"""Raw single-contest collector for snapshot v3."""

from __future__ import annotations

import csv
import datetime
import logging
import os
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, cast
from zoneinfo import ZoneInfo

from dfs_common import state

from dk_results.analytics.contest_metrics import average_remaining_salary
from dk_results.domain.contest_standings import parse_contest_standings
from dk_results.domain.sport import Sport
from dk_results.draftkings import DraftKings as Draftkings
from dk_results.paths import repo_file
from dk_results.persistence.contestdatabase import ContestDatabase, ContestRow
from dk_results.services.snapshot_v3 import sections
from dk_results.services.snapshot_v3.constants import DEFAULT_STANDINGS_LIMIT
from dk_results.services.snapshot_v3.normalize import (
    is_live_from_slot,
    normalize_name,
    slug,
    to_float,
    to_utc_iso,
)
from dk_results.vip_lineups import fetch_vip_lineups, load_vips

logger = logging.getLogger(__name__)

CONTEST_DIR = str(repo_file("contests"))
SALARY_DIR = str(repo_file("salary"))
COOKIES_FILE = str(repo_file("pickled_cookies_works.txt"))
CANDIDATE_LIMIT = 5


@dataclass(frozen=True)
class CollectedSnapshot:
    """Normalized collection result crossing into snapshot derivation/building."""

    bundle: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return dict(self.bundle)


def _sport_choices() -> dict[str, type[Sport]]:
    from dk_results.domain.sport import get_sport_choices

    return {name.upper(): sport for name, sport in get_sport_choices().items()}


def _build_selection_reason(
    *,
    mode: str,
    sport: str,
    min_entry_fee: int,
    keyword: str,
    selected_from_candidate_count: int,
    contest_id: int | None = None,
) -> dict[str, Any]:
    criteria: dict[str, Any] = {
        "sport": sport,
        "min_entry_fee": min_entry_fee,
        "keyword": keyword,
        "status_window": "start_date <= now && completed=0",
        "primary_preference": "entry_fee >= min_entry_fee then fallback below min",
    }
    if mode == "explicit_id":
        criteria = {"contest_id": str(contest_id) if contest_id is not None else None}

    return {
        "mode": mode,
        "criteria": criteria,
        "tie_breakers": [
            "entry_fee desc",
            "entries desc",
            "start_date desc",
            "dk_id desc",
        ],
        "selected_from_candidate_count": selected_from_candidate_count,
    }


def _summarize_candidates(rows: list[tuple], top_n: int = CANDIDATE_LIMIT) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for row in rows:
        contest_id, name, entry_fee, start_date, entries, selection_priority = row
        normalized.append(
            {
                "contest_id": str(contest_id),
                "name": name,
                "entry_fee": entry_fee,
                "entries": entries,
                "start_time_utc": to_utc_iso(start_date),
                "selection_priority": int(selection_priority),
            }
        )

    normalized.sort(
        key=lambda item: (
            item["selection_priority"],
            -int(item["entry_fee"] or 0),
            -int(item["entries"] or 0),
            item["contest_id"],
        )
    )
    return normalized[:top_n]


def _first_not_blank(*values: Any) -> Any:
    for value in values:
        if value not in (None, ""):
            return value
    return None


def _contest_row_from_detail(dk_id: int, detail: dict[str, Any]) -> ContestRow:
    contest_detail = detail.get("contestDetail", {})
    payout_summary = contest_detail.get("payoutSummary") or []
    positions_paid = None
    if payout_summary:
        positions_paid = payout_summary[0].get("maxPosition")
    start_time = contest_detail.get("contestStartTime")
    prize_pool = _first_not_blank(
        contest_detail.get("totalPrizePool"),
        contest_detail.get("totalPrizes"),
        contest_detail.get("totalPayouts"),
        contest_detail.get("totalPayout"),
        contest_detail.get("prizePool"),
        contest_detail.get("payout"),
    )
    max_entries_per_user = _first_not_blank(
        contest_detail.get("maxEntriesPerUser"),
        contest_detail.get("maximumEntriesPerUser"),
        contest_detail.get("maxEntriesPerPerson"),
        contest_detail.get("maxEntryCount"),
    )
    return ContestRow(
        dk_id=dk_id,
        name=contest_detail.get("name"),
        draft_group=contest_detail.get("draftGroupId"),
        positions_paid=positions_paid,
        start_date=start_time,
        entry_fee=contest_detail.get("entryFee"),
        entries=contest_detail.get("maximumEntries"),
        contest_state=contest_detail.get("contestState") or contest_detail.get("contestStatus"),
        contest_completed=contest_detail.get("isCompleted"),
        prize_pool=prize_pool,
        max_entries_per_user=max_entries_per_user,
    )


def _dollars_to_cents_half_up(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    cents = (amount * Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    try:
        return int(cents)
    except (TypeError, ValueError):
        return None


def _leaderboard_row_payout_cents(row: dict[str, Any]) -> int | None:
    winning_value = _dollars_to_cents_half_up(row.get("winningValue"))
    if winning_value is not None:
        return winning_value

    winnings = row.get("winnings")
    if isinstance(winnings, list):
        cash_total = 0
        found_cash = False
        for payout in winnings:
            if not isinstance(payout, dict):
                continue
            payout_kind = _first_not_blank(payout.get("payoutType"), payout.get("description"))
            if payout_kind is not None and "cash" not in str(payout_kind).lower():
                continue
            value = _first_not_blank(payout.get("winningValue"), payout.get("value"), payout.get("amount"))
            cents = _dollars_to_cents_half_up(value)
            if cents is not None:
                cash_total += cents
                found_cash = True
        if found_cash:
            return cash_total

    for candidate in (row.get("payout"), row.get("cash")):
        cents = _dollars_to_cents_half_up(candidate)
        if cents is not None:
            return cents
    return None


def _leaderboard_payout_map(payload: dict[str, Any]) -> dict[str, int]:
    results: dict[str, int] = {}
    rows = payload.get("contestStandings")
    if not isinstance(rows, list):
        rows = payload.get("standings")
    if not isinstance(rows, list):
        return results
    for row in rows:
        if not isinstance(row, dict):
            continue
        entry_key = row.get("entryKey") or row.get("entryId") or row.get("entry_id")
        if entry_key in (None, ""):
            continue
        payout_cents = _leaderboard_row_payout_cents(row)
        if payout_cents is None:
            continue
        results[str(entry_key)] = payout_cents
    return results


def _normalize_contest_state(raw_state: Any, completed: Any) -> str | None:
    if completed in (1, True, "1", "true", "True"):
        return "completed"
    text = str(raw_state or "").strip().lower()
    if not text:
        return None
    if text in {"live", "in progress", "in_progress", "started"}:
        return "live"
    if text in {"completed", "complete", "final"}:
        return "completed"
    if text in {"cancelled", "canceled"}:
        return "cancelled"
    if text in {"scheduled", "upcoming", "open"}:
        return "upcoming"
    return None


def _derive_composite_player_key(sport: str, row: dict[str, Any]) -> str | None:
    name_slug = slug(row.get("name") or row.get("player_name"))
    if not name_slug:
        return None
    team_slug = slug(row.get("team") or row.get("team_abbv")) or "na"
    pos_slug = slug(row.get("position") or row.get("pos")) or "na"
    salary_num = to_float(row.get("salary"))
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

    return normalized_rows


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
    normalized: dict[str, Any] = {
        key: str(value)
        for key, value in {
            "display_name": display_name,
            "entry_key": entry_key,
            "vip_entry_key": vip_entry_key,
        }.items()
        if value not in (None, "")
    }
    for key in ("rank", "pts", "pmr"):
        if row.get(key) not in (None, ""):
            normalized[key] = row[key]
    players_live = [
        live_slot
        for slot in _vip_players_source(row)
        if (live_slot := _normalize_vip_player_slot(slot, sport, unique_name_to_player_key))
    ]
    if players_live:
        normalized["players_live"] = players_live
    return normalized


def _vip_players_source(row: dict[str, Any]) -> list[Any]:
    for key in ("players_live", "lineup", "players"):
        value = row.get(key)
        if isinstance(value, list):
            return value
    return []


def _normalize_vip_player_slot(
    slot: Any, sport: str, unique_name_to_player_key: dict[str, str]
) -> dict[str, Any] | None:
    if not isinstance(slot, dict):
        return None
    player_name = slot.get("player_name") or slot.get("name")
    if player_name in (None, ""):
        return None
    player_key = slot.get("player_key")
    if player_key in (None, ""):
        player_key = unique_name_to_player_key.get(normalize_name(player_name))
    if player_key in (None, ""):
        player_key = _derive_composite_player_key(sport, {**slot, "player_name": player_name})
    live_slot: dict[str, Any] = {"player_name": str(player_name)}
    if player_key not in (None, ""):
        live_slot["player_key"] = str(player_key)
    salary = to_float(slot.get("salary"))
    if salary is not None:
        live_slot["salary"] = int(round(salary))
    live_slot["is_live"] = is_live_from_slot(slot)
    return live_slot


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
            keys_by_name.setdefault(normalize_name(player_name), set()).add(str(player_key))

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
            player_key = unique_name_to_player_key.get(normalize_name(player_name))
        if player_key not in (None, ""):
            mapped["player_key"] = str(player_key)
        normalized_rows.append(mapped)
    return normalized_rows


@dataclass(frozen=True)
class _ResolvedContest:
    """Contest identity and metadata resolved from the DB (and DK detail fallback)."""

    mode: str
    candidate_rows: list[tuple]
    dk_id: Any
    contest_name: Any
    draft_group: Any
    positions_paid: Any
    start_date: Any
    entry_fee: Any
    contest_state: Any
    contest_completed: Any
    prize_pool: Any
    max_entries: Any
    max_entries_per_user: Any


def _select_contest(
    *,
    sport_cls: type[Sport],
    contest_db: ContestDatabase | None,
    contest_id: int | None,
    dk: Draftkings,
) -> _ResolvedContest:
    """Resolve which contest to snapshot and merge its DB/detail metadata."""
    candidate_rows: list[tuple] = []
    if contest_db is not None:
        candidate_rows = contest_db.get_live_contest_candidates(
            sport_cls.name,
            entry_fee=sport_cls.sheet_min_entry_fee,
            keyword=sport_cls.keyword,
            limit=CANDIDATE_LIMIT,
        )

    mode = "primary_live"
    selected: ContestRow | None = None
    if contest_id is not None:
        mode = "explicit_id"
        if contest_db is not None:
            selected = contest_db.get_contest_by_id(int(contest_id))
        if not selected:
            selected = _contest_row_from_detail(int(contest_id), dk.get_contest_detail(int(contest_id)))
    else:
        if contest_db is None:
            raise RuntimeError("Contest DB unavailable for primary live selection")
        live = contest_db.get_live_contest(sport_cls.name, sport_cls.sheet_min_entry_fee, sport_cls.keyword)
        if live:
            selected = contest_db.get_contest_by_id(int(live[0]))

    if not selected:
        raise RuntimeError(f"No contest found for sport={sport_cls.name}")

    dk_id = selected.dk_id
    contest_name = selected.name
    draft_group = selected.draft_group
    positions_paid = selected.positions_paid
    start_date = selected.start_date
    entry_fee = selected.entry_fee
    contest_state = selected.contest_state
    contest_completed = selected.contest_completed
    prize_pool = selected.prize_pool if selected.prize_pool not in (None, "") else None
    max_entries = selected.entries
    max_entries_per_user = selected.max_entries_per_user if selected.max_entries_per_user not in (None, "") else None
    if contest_db is not None:
        state_row = contest_db.get_contest_state(int(dk_id))
        if state_row:
            contest_state, contest_completed = state_row
        contract_metadata = contest_db.get_contest_contract_metadata(int(dk_id))
        if contract_metadata:
            prize_pool, contest_capacity, per_user_limit, _db_entry_count = contract_metadata
            if contest_capacity not in (None, ""):
                max_entries = contest_capacity
            if per_user_limit not in (None, ""):
                max_entries_per_user = per_user_limit

    return _ResolvedContest(
        mode=mode,
        candidate_rows=candidate_rows,
        dk_id=dk_id,
        contest_name=contest_name,
        draft_group=draft_group,
        positions_paid=positions_paid,
        start_date=start_date,
        entry_fee=entry_fee,
        contest_state=contest_state,
        contest_completed=contest_completed,
        prize_pool=prize_pool,
        max_entries=max_entries,
        max_entries_per_user=max_entries_per_user,
    )


def _fetch_leaderboard_payouts(dk: Draftkings, dk_id: Any) -> dict[str, int]:
    """Read the leaderboard payout map, returning an empty map on any failure."""
    try:
        leaderboard_payload = dk.get_leaderboard(int(dk_id))
        if isinstance(leaderboard_payload, dict):
            return _leaderboard_payout_map(leaderboard_payload)
    except Exception:
        logger.warning("leaderboard payout lookup failed for contest_id=%s", dk_id, exc_info=True)
    return {}


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
            "state": _normalize_contest_state(resolved.contest_state, resolved.contest_completed),
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


def _collect_source_snapshot(
    *,
    sport: str,
    contest_id: int | None = None,
    standings_limit: int = DEFAULT_STANDINGS_LIMIT,
    dk: Draftkings | None = None,
    contest_db: ContestDatabase | None = None,
) -> dict[str, Any]:
    sport_map = _sport_choices()
    sport_cls = sport_map[sport.upper()]
    owns_db = False
    if contest_db is None:
        try:
            contest_db = ContestDatabase(str(state.contests_db_path()))
            owns_db = True
        except Exception:
            contest_db = None

    try:
        dk = dk or Draftkings()
        resolved = _select_contest(
            sport_cls=sport_cls,
            contest_db=contest_db,
            contest_id=contest_id,
            dk=dk,
        )
        dk_id = resolved.dk_id
        draft_group = resolved.draft_group
        logger.info("selected contest id=%s mode=%s", dk_id, resolved.mode)

        now_et = datetime.datetime.now(ZoneInfo("America/New_York"))
        salary_path = os.path.join(SALARY_DIR, f"DKSalaries_{sport_cls.name}_{now_et:%A}.csv")
        if draft_group:
            dk.download_salary_csv(sport_cls.name, draft_group, salary_path)

        standings_rows = dk.download_contest_rows(
            int(dk_id),
            timeout=30,
            cookies_dump_file=COOKIES_FILE,
            contest_dir=CONTEST_DIR,
        )
        if not standings_rows:
            raise RuntimeError(f"Contest standings unavailable for contest_id={dk_id}")
        leaderboard_payout_by_entry = _fetch_leaderboard_payouts(dk, dk_id)

        vips = load_vips()
        with open(salary_path, newline="", encoding="utf-8") as salary_file:
            salary_rows = list(csv.reader(salary_file))
        results = parse_contest_standings(
            sport_cls,
            salary_rows,
            standings_rows,
            positions_paid=resolved.positions_paid,
            vips=vips,
        )

        vip_entries: dict[str, dict[str, Any]] = {}
        for vip in results.vip_list:
            if not vip.name or not vip.player_id:
                continue
            vip_entries[vip.name] = {
                "entry_key": vip.player_id,
                "pmr": vip.pmr,
                "rank": vip.rank,
                "pts": vip.pts,
            }

        player_salary_map = {name: player.salary for name, player in results.players.items()}
        vip_lineups = (
            fetch_vip_lineups(
                int(dk_id),
                int(draft_group),
                dk,
                vips=vips,
                vip_entries=vip_entries,
                player_salary_map=player_salary_map,
            )
            if draft_group
            else []
        )

        vip_lookup = {vip.name for vip in results.vip_list}
        vip_lineup_rows: list[dict[str, Any]] = [
            cast(dict[str, Any], row) for row in vip_lineups if isinstance(row, dict)
        ]
        vip_points_by_entry = _build_vip_points_by_entry(vip_lineup_rows, results.vip_list)

        full_standings = sections.build_standings_rows(
            results,
            leaderboard_payout_by_entry=leaderboard_payout_by_entry,
            vip_lookup=vip_lookup,
            vip_points_by_entry=vip_points_by_entry,
        )
        players = sections.build_players(results)

        ownership_remaining_total = _compute_ownership_remaining_total(full_standings)
        avg_salary_per_player_remaining = average_remaining_salary(results.users)
        top_remaining_players = sections.build_top_remaining_players(results)
        watchlist_entries = sections.build_watchlist(full_standings)

        standings, truncation = _apply_truncation(full_standings, standings_limit)

        cash_line = sections.build_cash_line(results, full_standings)
        train_clusters = sections.build_train_clusters(results)

        return _assemble_source_bundle(
            sport_cls=sport_cls,
            resolved=resolved,
            dk_id=dk_id,
            draft_group=draft_group,
            cash_line=cash_line,
            vip_lineups=vip_lineups,
            players=players,
            ownership_remaining_total=ownership_remaining_total,
            avg_salary_per_player_remaining=avg_salary_per_player_remaining,
            non_cashing_user_count=results.non_cashing_users,
            non_cashing_avg_pmr=results.non_cashing_avg_pmr,
            watchlist_entries=watchlist_entries,
            top_remaining_players=top_remaining_players,
            train_clusters=train_clusters,
            standings=standings,
            truncation=truncation,
        )
    finally:
        if owns_db and contest_db is not None:
            contest_db.close()


def collect_snapshot(
    *,
    sport: str,
    contest_id: int | None = None,
    standings_limit: int = DEFAULT_STANDINGS_LIMIT,
) -> CollectedSnapshot:
    raw = _collect_source_snapshot(
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
    return CollectedSnapshot(
        bundle={
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
    )


def collect_raw_bundle(
    *,
    sport: str,
    contest_id: int | None = None,
    standings_limit: int = DEFAULT_STANDINGS_LIMIT,
) -> dict[str, Any]:
    """Compatibility wrapper returning the normalized bundle mapping."""

    return collect_snapshot(sport=sport, contest_id=contest_id, standings_limit=standings_limit).as_dict()
