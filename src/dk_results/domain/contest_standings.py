"""Pure standings parser: salary rows + standings rows → ContestStandings."""

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Type

from dfs_common.sheets import NumberFormat

from .dfs_sheet_domain import CellFormat
from .lineup import Lineup, LockedSlot, normalize_name, parse_lineup_string
from .player import Player
from .sport import Sport
from .user import User


@dataclass(frozen=True)
class ContestStandings:
    players: dict[str, Player]
    users: list[User]
    vip_list: list[User]
    positions_paid: int | None
    min_rank: int
    min_cash_pts: float
    non_cashing_users: int
    non_cashing_avg_pmr: float
    non_cashing_players: dict[str, int]


def _coerce_positions_paid(positions_paid: Any) -> int | None:
    if positions_paid is None:
        return None
    if isinstance(positions_paid, bool):
        return int(positions_paid)
    if isinstance(positions_paid, int):
        return positions_paid
    if isinstance(positions_paid, float):
        return int(positions_paid) if positions_paid.is_integer() else None
    if isinstance(positions_paid, str):
        value = positions_paid.strip()
        if not value:
            return None
        try:
            return int(value)
        except ValueError:
            try:
                float_value = float(value)
            except ValueError:
                return None
            return int(float_value) if float_value.is_integer() else None
    return None


def _parse_salary_rows(rows: Iterable[list[str]]) -> dict[str, Player]:
    players: dict[str, Player] = {}
    rows_iter = iter(rows)
    header = next(rows_iter, None)
    if not header:
        return players

    header_indexes = {str(column).removeprefix("\ufeff").strip().lower(): index for index, column in enumerate(header)}
    required_columns = {
        "position": ("position",),
        "name": ("name",),
        "roster position": ("roster position", "roster pos"),
        "salary": ("salary",),
        "game info": ("game info",),
        "team": ("teamabbrev", "team"),
    }
    missing_columns = [
        label for label, aliases in required_columns.items() if not any(alias in header_indexes for alias in aliases)
    ]
    if missing_columns:
        raise ValueError(f"Salary CSV is missing required columns: {', '.join(missing_columns)}")

    def index_for(*aliases: str) -> int:
        return next(header_indexes[alias] for alias in aliases if alias in header_indexes)

    position_index = index_for("position")
    name_index = index_for("name")
    roster_position_index = index_for("roster position", "roster pos")
    salary_index = index_for("salary")
    game_info_index = index_for("game info")
    team_index = index_for("teamabbrev", "team")
    max_required_index = max(
        position_index,
        name_index,
        roster_position_index,
        salary_index,
        game_info_index,
        team_index,
    )

    for row_number, row in enumerate(rows_iter, start=2):
        if not row or all(not str(value).strip() for value in row):
            continue
        if len(row) <= max_required_index:
            raise ValueError(
                f"Salary CSV row {row_number} has {len(row)} columns; expected at least {max_required_index + 1}"
            )

        pos = row[position_index]
        name = row[name_index]
        roster_pos = row[roster_position_index]
        salary = row[salary_index]
        game_info = row[game_info_index]
        team_abbv = row[team_index]
        name = normalize_name(name)
        players[name] = Player(name, pos, roster_pos, salary, game_info, team_abbv)
    return players


def _extract_player_stats(row: list[str]) -> tuple[str, str, float, float] | None:
    if len(row) < 10:
        return None
    raw_name = str(row[7]).strip()
    raw_pos = str(row[8]).strip() if len(row) > 8 else ""
    raw_ownership = str(row[9]).strip() if len(row) > 9 else ""
    raw_fpts = str(row[10]).strip() if len(row) > 10 else ""
    if not raw_name or not raw_ownership:
        return None
    try:
        ownership_pct = float(raw_ownership.replace("%", ""))
    except (TypeError, ValueError):
        return None
    fpts = 0.0
    if raw_fpts:
        try:
            fpts = float(raw_fpts)
        except (TypeError, ValueError):
            fpts = 0.0
    return normalize_name(raw_name), raw_pos, ownership_pct, fpts


def _accumulate_player_stats(
    row: list[str],
    aggregated: dict[str, dict[str, Any]],
) -> None:
    stats = _extract_player_stats(row)
    if not stats:
        return
    name, position, ownership_pct, fpts = stats
    player_agg = aggregated.setdefault(
        name,
        {"ownership_pct_sum": 0.0, "positions": set(), "fpts": 0.0, "row_count": 0},
    )
    player_agg["ownership_pct_sum"] += ownership_pct
    if position:
        player_agg["positions"].add(position)
    player_agg["fpts"] = max(float(player_agg["fpts"]), fpts)
    player_agg["row_count"] += 1


def _merge_positions(sport: Sport | Type[Sport], positions: set[str], fallback: str) -> str:
    if not positions:
        return fallback
    ordered_positions = tuple(dict.fromkeys(sport.positions))
    order_map = {pos: idx for idx, pos in enumerate(ordered_positions)}
    merged = sorted(positions, key=lambda pos: (order_map.get(pos, len(order_map)), pos))
    return "/".join(merged)


def _apply_aggregated_player_stats(
    sport: Sport | Type[Sport],
    players: dict[str, Player],
    aggregated: dict[str, dict[str, Any]],
    logger: logging.Logger,
) -> None:
    for name, stats in aggregated.items():
        player = players.get(name)
        if player is None:
            logger.error("Player %s not found in players[] dict", name)
            continue
        ownership_pct_sum = float(stats["ownership_pct_sum"])
        merged_position = _merge_positions(sport, set(stats["positions"]), player.pos)
        player.standings_pos = merged_position
        player.ownership = ownership_pct_sum / 100
        player.fpts = float(stats["fpts"])
        if player.fpts > 0:
            player.value = player.fpts / (player.salary / 1000)
        else:
            player.value = 0
        player.matchup_info = player.get_matchup_info()
        if ownership_pct_sum > 100:
            logger.warning(
                "Ownership exceeds 100%% for %s: %.2f%% across %d rows (positions: %s)",
                name,
                ownership_pct_sum,
                int(stats["row_count"]),
                merged_position,
            )


def _add_to_dict(player: Player, d: dict[str, int]) -> dict[str, int]:
    d[player.name] = d.get(player.name, 0) + 1
    return d


def _parse_standing_user(
    sport: Sport | Type[Sport], players: dict[str, Player], row: list[str]
) -> tuple[User, int | None, float | None]:
    rank, player_id, name, pmr, points, lineup = row[:6]
    parsed_rank: int | None = None
    parsed_points: float | None = None
    if rank:
        try:
            parsed_rank = int(rank)
        except (TypeError, ValueError):
            pass
    if points:
        try:
            parsed_points = float(points)
        except (TypeError, ValueError):
            pass
    lineupobj = Lineup(sport, players, lineup)
    user = User(parsed_rank, player_id, name, pmr, parsed_points, lineup)
    user.set_lineup_obj(lineupobj)
    return user, parsed_rank, parsed_points


def _record_non_cashing_user(
    sport: Sport | Type[Sport],
    players: dict[str, Player],
    lineup: str,
    non_cashing_players: dict[str, int],
    showdown_captains: dict[str, int],
) -> None:
    if sport.name not in ["NFL", "NFLShowdown", "CFB", "NBA"]:
        return
    for player in parse_lineup_string(sport, players, lineup):
        if isinstance(player, LockedSlot):
            continue
        if player.pos == "CPT":
            _add_to_dict(player, showdown_captains)
        if player.game_info != "Final":
            _add_to_dict(player, non_cashing_players)


def _update_cash_stats(
    positions_paid: int | None,
    parsed_rank: int | None,
    parsed_points: float | None,
    pmr: str,
    sport: Sport | Type[Sport],
    players: dict[str, Player],
    lineup: str,
    non_cashing_players: dict[str, int],
    showdown_captains: dict[str, int],
    min_rank: int,
    min_cash_pts: float,
    non_cashing_total_pmr: float,
) -> tuple[int, float, float, int]:
    if positions_paid is None or parsed_rank is None or parsed_points is None:
        return min_rank, min_cash_pts, non_cashing_total_pmr, 0
    if positions_paid >= parsed_rank and min_cash_pts > parsed_points:
        return parsed_rank, parsed_points, non_cashing_total_pmr, 0
    _record_non_cashing_user(sport, players, lineup, non_cashing_players, showdown_captains)
    return min_rank, min_cash_pts, non_cashing_total_pmr + float(pmr), 1


def _parse_standings_rows(
    sport: Sport | Type[Sport],
    players: dict[str, Player],
    standings: Iterable[list[str]],
    positions_paid: int | None,
    vips: list[str],
    logger: logging.Logger,
) -> tuple[list[User], list[User], int, float, int, float, dict[str, int]]:
    standings_iter = iter(standings)
    next(standings_iter, None)

    showdown_captains: dict[str, int] = {}
    aggregated_player_stats: dict[str, dict[str, Any]] = {}

    users: list[User] = []
    vip_list: list[User] = []
    min_rank = 0
    min_cash_pts = 1000.0
    non_cashing_players: dict[str, int] = {}
    non_cashing_users = 0
    non_cashing_total_pmr = 0.0

    for row in standings_iter:
        if not row:
            continue
        if len(row) < 6:
            continue
        core_blank = all(str(col).strip() == "" for col in row[:6])
        if core_blank:
            _accumulate_player_stats(row, aggregated_player_stats)
            continue

        user, parsed_rank, parsed_points = _parse_standing_user(sport, players, row)
        users.append(user)

        if user.name in vips:
            vip_list.append(user)

        min_rank, min_cash_pts, non_cashing_total_pmr, added_non_cashing = _update_cash_stats(
            positions_paid,
            parsed_rank,
            parsed_points,
            row[3],
            sport,
            players,
            row[5],
            non_cashing_players,
            showdown_captains,
            min_rank,
            min_cash_pts,
            non_cashing_total_pmr,
        )
        non_cashing_users += added_non_cashing

        _accumulate_player_stats(row, aggregated_player_stats)

    _apply_aggregated_player_stats(sport, players, aggregated_player_stats, logger)

    non_cashing_avg_pmr = 0.0
    if non_cashing_users > 0 and non_cashing_total_pmr > 0:
        non_cashing_avg_pmr = non_cashing_total_pmr / non_cashing_users

    logger.debug(
        "non_cashing users=%d total_pmr=%.2f avg_pmr=%.2f",
        non_cashing_users,
        non_cashing_total_pmr,
        non_cashing_avg_pmr,
    )

    if sport.name == "NFLShowdown":
        sorted_captains = dict(sorted(showdown_captains.items(), key=lambda item: item[1], reverse=True))
        top_ten_cpts = list(sorted_captains)[:10]
        logger.debug("Top 10 captains:")
        for cpt in top_ten_cpts:
            num_users = len(users)
            percent = float(showdown_captains[cpt] / num_users) * 100
            message = "{}: {:0.2f}% [{}/{}]".format(cpt, percent, showdown_captains[cpt], num_users)
            logger.debug(message)
            print(message)

    return (
        users,
        vip_list,
        min_rank,
        min_cash_pts,
        non_cashing_users,
        non_cashing_avg_pmr,
        non_cashing_players,
    )


def parse_contest_standings(
    sport: Sport | Type[Sport],
    salary_rows: Iterable[list[str]],
    standings_rows: Iterable[list[str]],
    positions_paid: Any = None,
    vips: list[str] | None = None,
    logger: logging.Logger | None = None,
) -> ContestStandings:
    """Parse salary and standings CSV rows into a ContestStandings."""
    log = logger or logging.getLogger(__name__)
    coerced_positions_paid = _coerce_positions_paid(positions_paid)
    vip_names = list(vips) if vips else []

    players = _parse_salary_rows(salary_rows)

    (
        users,
        vip_list,
        min_rank,
        min_cash_pts,
        non_cashing_users,
        non_cashing_avg_pmr,
        non_cashing_players,
    ) = _parse_standings_rows(sport, players, standings_rows, coerced_positions_paid, vip_names, log)

    for vip in vip_list:
        salary_rem = vip.salary
        vip.set_lineup(parse_lineup_string(sport, players, vip.lineup_str))
        lineup_fmt = "/".join(f"{p.pos} {p.name.split()[-1]}" for p in vip.lineup) if vip.lineup else vip.lineup_str
        log.debug(
            "vip_user name=%s rank=%s pmr=%s pts=%s salary_rem=%d lineup=%r",
            vip.name,
            vip.rank,
            vip.pmr,
            vip.pts,
            salary_rem,
            lineup_fmt,
        )

    return ContestStandings(
        players=players,
        users=users,
        vip_list=vip_list,
        positions_paid=coerced_positions_paid,
        min_rank=min_rank,
        min_cash_pts=min_cash_pts,
        non_cashing_users=non_cashing_users,
        non_cashing_avg_pmr=non_cashing_avg_pmr,
        non_cashing_players=non_cashing_players,
    )


# Column offset of "Salary" within a `Player.writeable` row, relative to the
# row's own start. PGA/GOLF write a shorter row than other sports.
def _standings_salary_col(sport_name: str) -> int:
    if sport_name in ("PGA", "GOLF") or "PGA" in sport_name:
        return 2
    return 4


def players_to_values(players: dict[str, Player], sport_name: str) -> tuple[list[list], list[CellFormat]]:
    """Return sheet-ready rows (sorted by ownership, zero-ownership filtered) and their format plan."""
    sorted_players = sorted(players, key=lambda x: players[x].ownership, reverse=True)
    values = [players[p].writeable(sport_name) for p in sorted_players if players[p].ownership > 0]
    salary_col = _standings_salary_col(sport_name)
    format_plan = [
        CellFormat(row=row, col=salary_col, number_format=NumberFormat.CURRENCY) for row in range(len(values))
    ]
    return values, format_plan
