"""Name types shared by the snapshot contract models."""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import GetCoreSchemaHandler, GetJsonSchemaHandler, StrictStr, StringConstraints
from pydantic.json_schema import JsonSchemaValue
from pydantic_core import PydanticCustomError, core_schema

PADDED_NAME_MESSAGE = "must not have leading or trailing whitespace"

_TRIMMED_PATTERN = r"^\S(?:[\s\S]*\S)?$"


def is_padded(name: str) -> bool:
    """True when the name has leading or trailing whitespace."""
    return name != name.strip()


class _NoPadding:
    """Reject leading or trailing whitespace with a readable error; the exported schema carries it as a pattern."""

    def __get_pydantic_core_schema__(self, source: Any, handler: GetCoreSchemaHandler) -> core_schema.CoreSchema:
        return core_schema.no_info_after_validator_function(self._check, handler(source))

    def __get_pydantic_json_schema__(
        self, schema: core_schema.CoreSchema, handler: GetJsonSchemaHandler
    ) -> JsonSchemaValue:
        return {**handler(schema), "pattern": _TRIMMED_PATTERN}

    @staticmethod
    def _check(value: str) -> str:
        if is_padded(value):
            raise PydanticCustomError("padded_name", PADDED_NAME_MESSAGE)
        return value


TrimmedName = Annotated[StrictStr, StringConstraints(min_length=1), _NoPadding()]
"""A non-empty name with no leading or trailing whitespace."""
