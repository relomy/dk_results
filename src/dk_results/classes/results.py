"""Create a Results object which contains the results for a given DraftKings contest."""

import csv
import io
import logging
import os
from collections.abc import Mapping
from datetime import datetime
from typing import Any, Iterable, Type

from .lineup import Lineup, normalize_name, parse_lineup_string
from .player import Player
from .sport import Sport
from .user import User


class Results:
    """Parse salary and standings data for a DraftKings contest."""

    @staticmethod
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

    def __init__(
        self,
        sport_obj: Sport | Type[Sport],
        contest_id: int,
        salary_csv_fn: str,
        positions_paid: int | None = None,
        salary_rows: list[list[str]] | None = None,
        standings_rows: list[list[str]] | None = None,
        vips: list[str] | None = None,
        logger: logging.Logger | None = None,
    ):
        self.logger = logger or logging.getLogger(__name__)

        self.sport_obj = sport_obj
        self.contest_id = contest_id
        self.players = {}  # dict for players found in salary and standings CSV
        self.users = []  # list of Users found in standings CSV
        self.positions_paid: int | None = self._coerce_positions_paid(positions_paid)
        self.name: str = ""

        self.min_rank = 0
        self.min_cash_pts = 1000.0

        # non cashing values (players outside the cash line)
        self.avg_cashless_pmr = 0
        self.non_cashing_players = {}
        self.non_cashing_users = 0
        self.non_cashing_total_pmr = 0
        self.non_cashing_avg_pmr = 0.0

        # dict of positions for each sport
        self.POSITIONS = {
            "XFL": ["QB", "RB", "WR", "FLEX", "DST"],
        }

        # if there's no salary file specified, use the sport/day for the filename
        if not salary_csv_fn:
            salary_csv_fn = f"DKSalaries_{self.sport_obj.sport_name}_{datetime.now():%A}.csv"

        if salary_rows is not None:
            self.parse_salary_rows(salary_rows)
        else:
            self.parse_salary_csv(salary_csv_fn)

        self.vips = list(vips) if vips else []
        self.vip_list = []  # list of VIPs found in standings CSV

        # contest_fn = 'contest-standings-73990354.csv'
        contest_dir = "contests"
        contest_fn = os.path.join(contest_dir, "contest-standings-{}.csv".format(self.contest_id))

        # this pulls the DK users and updates the players stats
        if standings_rows is not None:
            self.parse_contest_standings_rows(standings_rows)
        else:
            self.parse_contest_standings_csv(contest_fn)

        for vip in self.vip_list:
            self.logger.debug("VIP: %s", vip)
            # vip.lineup = self.parse_lineup_string(vip.lineup_str)
            vip.set_lineup(self.parse_lineup_string(vip.lineup_str))

        # for k, v in self.players_dict.items():
        #     self.logger.debug("{}: {}".format(k, v))

    def parse_lineup_string(self, lineup_str: str) -> list[Player]:
        """Parse VIP's lineup_str and return list of Players."""
        return parse_lineup_string(self.sport_obj, self.players, lineup_str)

    def parse_salary_csv(self, filename: str) -> None:
        """Parse CSV containing players and salary information."""
        with open(filename, mode="r") as fp:
            cr = csv.reader(fp, delimiter=",")
            self.parse_salary_rows(cr)

    def parse_salary_rows(self, rows: Iterable[list[str]]) -> None:
        """Parse salary rows, including header row at index 0."""
        rows_iter = iter(rows)
        next(rows_iter, None)
        for row in rows_iter:
            if len(row) < 2:
                continue
            # TODO: might use roster_pos in the future
            # pos, _, name, _, roster_pos, salary, game_info, team_abbv, appg
            pos, _, name, _, roster_pos, salary, game_info, team_abbv, _ = row

            # ensure name doesn't have any weird characters
            name = normalize_name(name)

            self.players[name] = Player(name, pos, roster_pos, salary, game_info, team_abbv)

    def parse_contest_standings_csv(self, filename: str) -> None:
        """Parse CSV containing contest standings and player ownership."""
        with open(filename, "rb") as csvfile:
            lines = io.TextIOWrapper(csvfile, encoding="utf-8", newline="\n")
            rdr = csv.reader(lines, delimiter=",")
            self.parse_contest_standings_rows(rdr)

    def parse_contest_standings_rows(self, standings: Iterable[list[str]]) -> None:
        """Parse contest standings rows, including header row at index 0."""
        standings_iter = iter(standings)
        next(standings_iter, None)

        # showdown only
        showdown_captains = {}
        aggregated_player_stats: dict[str, dict[str, Any]] = {}

        # create a copy of player list
        # player_list = self.players
        for row in standings_iter:
            # catch empty rows
            if not row:
                continue
            if len(row) < 6:
                continue
            core_blank = all(str(col).strip() == "" for col in row[:6])
            if core_blank:
                # DK exports may include player-stat-only rows with blank entry columns.
                self._accumulate_player_stats(row, aggregated_player_stats)
                continue

            rank, player_id, name, pmr, points, lineup = row[:6]
            parsed_rank: int | None = None
            parsed_points: float | None = None

            if rank:
                try:
                    parsed_rank = int(rank)
                    rank = parsed_rank
                except (TypeError, ValueError):
                    parsed_rank = None
            if points:
                try:
                    parsed_points = float(points)
                    points = parsed_points
                except (TypeError, ValueError):
                    parsed_points = None

            # create User object and append to users list
            lineupobj = Lineup(self.sport_obj, self.players, lineup)
            user = User(rank, player_id, name, pmr, points, lineup)
            user.set_lineup_obj(lineupobj)
            self.users.append(user)

            # find lineup for friends
            if name in self.vips:
                # if we found a VIP, add them to the VIP list
                self.logger.info("found VIP %s", name)
                self.vip_list.append(user)

            # keep track of minimum pts to cash
            if self.positions_paid is not None and parsed_rank is not None and parsed_points is not None:
                # set minimum cash pts
                if self.positions_paid >= parsed_rank and self.min_cash_pts > parsed_points:
                    self.min_rank = parsed_rank
                    self.min_cash_pts = parsed_points
                else:
                    self.non_cashing_total_pmr += float(pmr)

                    # let's only parse lineups for NFL right now
                    if self.sport_obj.name in [
                        "NFL",
                        "NFLShowdown",
                        "CFB",
                        "NBA",
                    ]:
                        # for those below minimum cash, let's find their players
                        lineup_players = self.parse_lineup_string(lineup)

                        for player in lineup_players:
                            if player.pos == "CPT":
                                showdown_captains = self.add_player_to_dict(player, showdown_captains)

                            # we only care about players that are not done yet
                            if player.game_info == "Final":
                                continue

                            self.non_cashing_players = self.add_player_to_dict(player, self.non_cashing_players)

                        self.non_cashing_users += 1

            self._accumulate_player_stats(row, aggregated_player_stats)

        self._apply_aggregated_player_stats(aggregated_player_stats)

        if self.non_cashing_users > 0 and self.non_cashing_total_pmr > 0:
            self.non_cashing_avg_pmr = self.non_cashing_total_pmr / self.non_cashing_users

        self.logger.debug(
            "non_cashing: users {} total_pmr: {} avg_pmr: {}".format(
                self.non_cashing_users,
                self.non_cashing_total_pmr,
                self.non_cashing_avg_pmr,
            )
        )

        if self.sport_obj.sport_name == "NFLShowdown":
            sorted_captains = {
                k: v
                for k, v in sorted(
                    showdown_captains.items(),
                    key=lambda item: item[1],
                    reverse=True,
                )
            }

            top_ten_cpts = list(sorted_captains)[:10]

            self.logger.info("Top 10 captains:")
            for cpt in top_ten_cpts:
                self.get_showdown_captain_percent(cpt, showdown_captains)

    def add_player_to_dict(self, player: Player, dictionary: dict[str, int]) -> dict[str, int]:
        if player.name not in dictionary:
            dictionary[player.name] = 0

        # add players
        dictionary[player.name] += 1

        return dictionary

    def get_showdown_captain_percent(self, player: str, showdown_captains: dict[str, int]) -> None:
        percent = 0.0
        num_users = len(self.users)
        percent = float(showdown_captains[player] / num_users) * 100
        print("{}: {:0.2f}% [{}/{}]".format(player, percent, showdown_captains[player], num_users))

    def load_standings(self, filename: str) -> list[list[str]]:
        """Load standings CSV and return list."""
        with open(filename, "rb") as csvfile:
            lines = io.TextIOWrapper(csvfile, encoding="utf-8", newline="\n")
            rdr = csv.reader(lines, delimiter=",")
            return list(rdr)

    def players_to_values(self, sport: str) -> list[list]:
        """Return list for DfsSheetService values."""
        # sort players by ownership
        sorted_players = sorted(self.players, key=lambda x: self.players[x].ownership, reverse=True)
        # for p in self.players.values():
        #     print(p.perc)
        #     print()
        return [self.players[p].writeable(sport) for p in sorted_players if self.players[p].ownership > 0]

    def get_players(self) -> dict[str, Player]:
        return self.players

    @staticmethod
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
        self,
        row: list[str],
        aggregated_player_stats: dict[str, dict[str, Any]],
    ) -> None:
        stats = self._extract_player_stats(row)
        if not stats:
            return

        name, position, ownership_pct, fpts = stats
        player_agg = aggregated_player_stats.setdefault(
            name,
            {
                "ownership_pct_sum": 0.0,
                "positions": set(),
                "fpts": 0.0,
                "row_count": 0,
            },
        )
        player_agg["ownership_pct_sum"] += ownership_pct
        if position:
            player_agg["positions"].add(position)
        player_agg["fpts"] = max(float(player_agg["fpts"]), fpts)
        player_agg["row_count"] += 1

    def _merge_positions(self, positions: set[str], fallback: str) -> str:
        if not positions:
            return fallback
        ordered_positions = tuple(dict.fromkeys(self.sport_obj.positions))
        order_map = {pos: idx for idx, pos in enumerate(ordered_positions)}
        merged = sorted(positions, key=lambda pos: (order_map.get(pos, len(order_map)), pos))
        return "/".join(merged)

    def _apply_aggregated_player_stats(self, aggregated_player_stats: Mapping[str, dict[str, Any]]) -> None:
        for name, stats in aggregated_player_stats.items():
            player = self.players.get(name)
            if player is None:
                self.logger.error("Player %s not found in players[] dict", name)
                continue

            ownership_pct_sum = float(stats["ownership_pct_sum"])
            merged_position = self._merge_positions(set(stats["positions"]), player.pos)
            player.standings_pos = merged_position
            player.ownership = ownership_pct_sum / 100
            player.fpts = float(stats["fpts"])

            if player.fpts > 0:
                player.value = player.fpts / (player.salary / 1000)
            else:
                player.value = 0
            player.matchup_info = player.get_matchup_info()

            if ownership_pct_sum > 100:
                self.logger.warning(
                    "Ownership exceeds 100%% for %s: %.2f%% across %d rows (positions: %s)",
                    name,
                    ownership_pct_sum,
                    int(stats["row_count"]),
                    merged_position,
                )
