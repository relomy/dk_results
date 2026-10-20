"""Raw single-contest collector for snapshot v3."""

from __future__ import annotations

import csv
import datetime
import logging
import os
from dataclasses import dataclass
from typing import Any
from zoneinfo import ZoneInfo

from dfs_common import state

from dk_results.domain.contest_standings import ContestStandings, parse_contest_standings
from dk_results.domain.draftables import Draftables
from dk_results.domain.sport import Sport
from dk_results.draftkings import DraftKings as Draftkings
from dk_results.draftkings.leaderboard import leaderboard_cash_cents
from dk_results.paths import repo_file
from dk_results.persistence.contestdatabase import ContestDatabase, ContestRow
from dk_results.services.snapshot_v3.constants import DEFAULT_STANDINGS_LIMIT
from dk_results.services.snapshot_v3.contest_selection import (
    CANDIDATE_LIMIT,
    _contest_row_from_detail,
    _ResolvedContest,
)
from dk_results.services.snapshot_v3.source_bundle import (
    _assemble_source_bundle,
    _build_source_metrics,
    _build_vip_points_by_entry,
)
from dk_results.services.snapshot_v3.vip_normalize import (
    _build_unique_name_to_player_key_from_vip_lineups,
    _merge_unique_name_to_player_keys,
    _normalize_ownership_top_lists,
    _normalize_players,
    _normalize_vip_lineup_rows,
)
from dk_results.vip_lineups import build_vip_entries, fetch_vip_lineups, load_vips, scorecard_facts_by_draftable_id

logger = logging.getLogger(__name__)

CONTEST_DIR = str(repo_file("contests"))
SALARY_DIR = str(repo_file("salary"))
COOKIES_FILE = str(repo_file("pickled_cookies_works.txt"))


@dataclass(frozen=True)
class CollectedSnapshot:
    """Normalized collection result crossing into snapshot derivation/building."""

    bundle: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return dict(self.bundle)


def _sport_choices() -> dict[str, type[Sport]]:
    from dk_results.domain.sport import get_sport_choices

    return {name.upper(): sport for name, sport in get_sport_choices().items()}


def _leaderboard_payout_map(payload: dict[str, Any]) -> dict[str, int]:
    results: dict[str, int] = {}
    rows = payload.get("leaderBoard")
    if not isinstance(rows, list):
        return results
    for row in rows:
        if not isinstance(row, dict):
            continue
        entry_key = row.get("entryKey") or row.get("entryId") or row.get("entry_id")
        if entry_key in (None, ""):
            continue
        payout_cents = leaderboard_cash_cents(row)
        if payout_cents is None:
            continue
        results[str(entry_key)] = payout_cents
    return results


def _resolve_selected_contest(
    *,
    sport_cls: type[Sport],
    contest_db: ContestDatabase | None,
    contest_id: int | None,
    dk: Draftkings,
) -> tuple[str, ContestRow | None]:
    if contest_id is not None:
        selected: ContestRow | None = None
        if contest_db is not None:
            selected = contest_db.get_contest_by_id(int(contest_id))
        if not selected:
            selected = _contest_row_from_detail(int(contest_id), dk.get_contest_detail(int(contest_id)))
        return "explicit_id", selected

    if contest_db is None:
        raise RuntimeError("Contest DB unavailable for primary live selection")
    live = contest_db.get_live_contest(sport_cls.name, sport_cls.sheet_min_entry_fee, sport_cls.keyword)
    selected = contest_db.get_contest_by_id(int(live[0])) if live else None
    return "primary_live", selected


def _resolve_contest_db_overrides(contest_db: ContestDatabase | None, selected: ContestRow) -> dict[str, Any]:
    contest_state = selected.contest_state
    contest_completed = selected.contest_completed
    prize_pool = selected.prize_pool if selected.prize_pool not in (None, "") else None
    max_entries = selected.entries
    max_entries_per_user = selected.max_entries_per_user if selected.max_entries_per_user not in (None, "") else None
    completed_at: str | None = None
    if contest_db is None:
        return {
            "contest_state": contest_state,
            "contest_completed": contest_completed,
            "prize_pool": prize_pool,
            "max_entries": max_entries,
            "max_entries_per_user": max_entries_per_user,
            "completed_at": completed_at,
        }

    state_row = contest_db.get_contest_state(int(selected.dk_id))
    if state_row:
        contest_state, contest_completed = state_row
    completed_at = contest_db.get_contest_completed_at(int(selected.dk_id))
    contract_metadata = contest_db.get_contest_contract_metadata(int(selected.dk_id))
    if contract_metadata:
        prize_pool, contest_capacity, per_user_limit, _db_entry_count = contract_metadata
        if contest_capacity not in (None, ""):
            max_entries = contest_capacity
        if per_user_limit not in (None, ""):
            max_entries_per_user = per_user_limit
    return {
        "contest_state": contest_state,
        "contest_completed": contest_completed,
        "prize_pool": prize_pool,
        "max_entries": max_entries,
        "max_entries_per_user": max_entries_per_user,
        "completed_at": completed_at,
    }


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

    mode, selected = _resolve_selected_contest(sport_cls=sport_cls, contest_db=contest_db, contest_id=contest_id, dk=dk)
    if not selected:
        raise RuntimeError(f"No contest found for sport={sport_cls.name}")

    overrides = _resolve_contest_db_overrides(contest_db, selected)

    return _ResolvedContest(
        mode=mode,
        candidate_rows=candidate_rows,
        dk_id=selected.dk_id,
        contest_name=selected.name,
        draft_group=selected.draft_group,
        positions_paid=selected.positions_paid,
        start_date=selected.start_date,
        entry_fee=selected.entry_fee,
        contest_state=overrides["contest_state"],
        contest_completed=overrides["contest_completed"],
        prize_pool=overrides["prize_pool"],
        max_entries=overrides["max_entries"],
        max_entries_per_user=overrides["max_entries_per_user"],
        completed_at=overrides["completed_at"],
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


def _fetch_matchups(dk: Draftkings, draft_group: Any) -> dict[str, str | None]:
    """Read the draftable ID -> Matchup lookup, returning an empty lookup on any failure."""
    if not draft_group:
        return {}
    try:
        return Draftables.from_payload(dk.get_draftables(int(draft_group))).matchups_by_draftable_id()
    except Exception:
        logger.warning("draftables matchup lookup failed for draft_group=%s", draft_group, exc_info=True)
    return {}


def _open_contest_db(contest_db: ContestDatabase | None) -> tuple[ContestDatabase | None, bool]:
    if contest_db is not None:
        return contest_db, False
    try:
        return ContestDatabase(str(state.contests_db_path())), True
    except Exception:
        return None, False


def _download_standings_rows(dk: Draftkings, dk_id: Any) -> list[list[str]]:
    standings_rows = dk.download_contest_rows(
        int(dk_id),
        timeout=30,
        cookies_dump_file=COOKIES_FILE,
        contest_dir=CONTEST_DIR,
    )
    if not standings_rows:
        raise RuntimeError(f"Contest standings unavailable for contest_id={dk_id}")
    return standings_rows


def _fetch_vip_lineups_for_contest(
    dk: Draftkings,
    dk_id: Any,
    draft_group: Any,
    vips: list[str],
    vip_entries: dict[str, dict[str, Any]],
    player_salary_map: dict[str, int],
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    """Fetch the VIP lineups as dict rows, plus the pool facts their Scorecards carry by draftable id."""
    if not draft_group:
        return [], {}
    lineups = fetch_vip_lineups(
        int(dk_id),
        int(draft_group),
        dk,
        vips=vips,
        vip_entries=vip_entries,
        player_salary_map=player_salary_map,
    )
    # The fetcher returns typed VipLineup objects; normalization works on dict rows.
    return [lineup.to_dict() for lineup in lineups], scorecard_facts_by_draftable_id(lineups)


def _resolve_contest_standings(
    standings: ContestStandings | None,
    *,
    sport_cls: type[Sport],
    salary_path: str,
    standings_rows: list[list[str]],
    positions_paid: Any,
    vips: list[str],
) -> ContestStandings:
    if standings is not None:
        return standings
    with open(salary_path, newline="", encoding="utf-8") as salary_file:
        salary_rows = list(csv.reader(salary_file))
    return parse_contest_standings(sport_cls, salary_rows, standings_rows, positions_paid=positions_paid, vips=vips)


def _collect_source_snapshot(
    *,
    sport: str,
    contest_id: int | None = None,
    standings_limit: int = DEFAULT_STANDINGS_LIMIT,
    dk: Draftkings | None = None,
    contest_db: ContestDatabase | None = None,
    standings: ContestStandings | None = None,
) -> dict[str, Any]:
    """Collect behind injectable edges, optionally using already-parsed standings."""
    sport_map = _sport_choices()
    sport_cls = sport_map[sport.upper()]
    contest_db, owns_db = _open_contest_db(contest_db)

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
        matchups = _fetch_matchups(dk, draft_group)

        standings_rows = _download_standings_rows(dk, dk_id)
        leaderboard_payout_by_entry = _fetch_leaderboard_payouts(dk, dk_id)

        vips = load_vips()
        results = _resolve_contest_standings(
            standings,
            sport_cls=sport_cls,
            salary_path=salary_path,
            standings_rows=standings_rows,
            positions_paid=resolved.positions_paid,
            vips=vips,
        )

        vip_entries = build_vip_entries(results.vip_list)
        player_salary_map = {name: player.salary for name, player in results.players.items()}
        vip_lineups, scorecard_facts = _fetch_vip_lineups_for_contest(
            dk, dk_id, draft_group, vips, vip_entries, player_salary_map
        )

        vip_lookup = {vip.name for vip in results.vip_list}
        vip_points_by_entry = _build_vip_points_by_entry(vip_lineups, results.vip_list)

        metrics = _build_source_metrics(
            results,
            leaderboard_payout_by_entry=leaderboard_payout_by_entry,
            vip_lookup=vip_lookup,
            vip_points_by_entry=vip_points_by_entry,
            matchups=matchups,
            scorecard_facts=scorecard_facts,
            standings_limit=standings_limit,
        )

        return _assemble_source_bundle(
            sport_cls=sport_cls,
            resolved=resolved,
            dk_id=dk_id,
            draft_group=draft_group,
            cash_line=metrics["cash_line"],
            vip_lineups=vip_lineups,
            players=metrics["players"],
            ownership_remaining_total=metrics["ownership_remaining_total"],
            field_remaining=metrics["field_remaining"],
            vip_remaining_by_entry_key=metrics["vip_remaining_by_entry_key"],
            vip_remaining_is_partial_by_entry_key=metrics["vip_remaining_is_partial_by_entry_key"],
            avg_salary_per_player_remaining=metrics["avg_salary_per_player_remaining"],
            non_cashing_user_count=results.non_cashing_users,
            non_cashing_avg_pmr=results.non_cashing_avg_pmr,
            watchlist_entries=metrics["watchlist_entries"],
            top_remaining_players=metrics["top_remaining_players"],
            train_clusters=metrics["train_clusters"],
            standings=metrics["standings"],
            truncation=metrics["truncation"],
        )
    finally:
        if owns_db and contest_db is not None:
            contest_db.close()


def _build_collected_bundle(
    raw: dict[str, Any],
    *,
    standings: list[dict[str, Any]],
    players: list[dict[str, Any]],
    ownership: dict[str, Any],
    vip_lineups: list[dict[str, Any]],
    train_clusters: list[dict[str, Any]],
) -> dict[str, Any]:
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
    ownership = _normalize_ownership_top_lists(dict(raw.get("ownership") or {}), unique_name_to_player_key)

    return CollectedSnapshot(
        bundle=_build_collected_bundle(
            raw,
            standings=standings,
            players=players,
            ownership=ownership,
            vip_lineups=vip_lineups,
            train_clusters=train_clusters,
        )
    )


def collect_raw_bundle(
    *,
    sport: str,
    contest_id: int | None = None,
    standings_limit: int = DEFAULT_STANDINGS_LIMIT,
) -> dict[str, Any]:
    """Compatibility wrapper returning the normalized bundle mapping."""

    return collect_snapshot(sport=sport, contest_id=contest_id, standings_limit=standings_limit).as_dict()
