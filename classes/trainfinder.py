import logging
import logging.config
from typing import Any

from .user import User


class TrainFinder:
    def __init__(
        self, Users: list[User], logger: logging.Logger | None = None
    ) -> None:
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

    def get_users_above_salary_spent(self, salary: int) -> dict[str, dict[str, Any]]:
        # users { data }
        # data: { pmr pts lineup count }
        return_users: dict[str, dict[str, Any]] = {}

        for user in self.Users:
            if user.salary <= salary:
                key = f"{user.pts}-{user.pmr}"
                if not key in return_users:
                    return_users[key] = {
                        "pos": 0,
                        "pmr": 0.0,
                        "pts": 0.0,
                        "lineup": None,
                        "count": 0,
                    }
                    return_users[key]["rank"] = user.rank
                    return_users[key]["pts"] = user.pts
                    return_users[key]["lineup"] = user.lineupobj
                    return_users[key]["pmr"] = user.pmr

                return_users[key]["count"] += 1

        return return_users
