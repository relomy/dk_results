import argparse
import datetime
from typing import Optional


def valid_date(date_string: str) -> datetime.datetime:
    """Validate and parse a date string in YYYY-MM-DD format."""
    try:
        return datetime.datetime.strptime(date_string, "%Y-%m-%d")
    except ValueError as exc:
        msg = "Not a valid date: '{0}'.".format(date_string)
        raise argparse.ArgumentTypeError(msg) from exc


def get_salary_date(draft_group: dict) -> datetime.date:
    """Get salary date from a draft-group payload."""
    return datetime.datetime.strptime(draft_group["StartDateEst"].split("T")[0], "%Y-%m-%d").date()


def is_time_between(
    begin_time: datetime.time,
    end_time: datetime.time,
    check_time: Optional[datetime.time] = None,
) -> bool:
    """Check whether check_time falls in the [begin_time, end_time] window."""
    check_time = check_time or datetime.datetime.now(datetime.timezone.utc).time()
    if begin_time < end_time:
        return begin_time <= check_time <= end_time
    return check_time >= begin_time or check_time <= end_time
