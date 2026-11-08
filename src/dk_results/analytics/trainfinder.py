import logging
from dataclasses import dataclass
from typing import Any

from dk_results.domain.user import User


@dataclass(frozen=True)
class TrainCluster:
    """Named result for users sharing points and remaining time."""

    cluster_key: str
    rank: int | None
    points: float | None
    pmr: float | str | None
    lineup: Any
    user_count: int
    entry_keys: tuple[str, ...] = ()


class TrainFinder:
    def __init__(self, Users: list[User], logger: logging.Logger | None = None) -> None:
        self.logger = logger or logging.getLogger(__name__)

        self.Users = Users

    def get_total_users(self) -> int:
        return len(self.Users)

    def get_total_users_above_salary(self, salary: int) -> int:
        count = 0

        for user in self.Users:
            if user.salary <= salary:
                count += 1

        return count

    def get_users_above_salary_spent(self, salary: int) -> dict[str, TrainCluster]:
        clusters: dict[str, TrainCluster] = {}

        for user in self.Users:
            if user.salary <= salary:
                key = f"{user.pts}-{user.pmr}"
                current = clusters.get(key)
                if current is None:
                    current = TrainCluster(key, user.rank, user.pts, user.pmr, user.lineupobj, 0)
                clusters[key] = TrainCluster(
                    current.cluster_key,
                    current.rank,
                    current.points,
                    current.pmr,
                    current.lineup,
                    current.user_count + 1,
                    (*current.entry_keys, str(user.player_id)),
                )

        return clusters
