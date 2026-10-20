"""Value predicates shared by the snapshot envelope validators.

Non-empty strings, ISO timestamps, finite numbers and the type test the required-field
checks use.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any


def _is_non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_valid_timestamp(value: Any) -> bool:
    if not _is_non_empty_string(value):
        return False
    try:
        datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def _has_type(value: Any, expected: type) -> bool:
    if expected is str:
        return _is_non_empty_string(value)
    if expected is int:
        return isinstance(value, int) and not isinstance(value, bool)
    return isinstance(value, expected)


def _is_finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
