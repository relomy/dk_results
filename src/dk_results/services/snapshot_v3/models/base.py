"""Shared building blocks for the snapshot contract models."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator
from pydantic_core import PydanticCustomError


def _drop_default(schema: dict[str, Any]) -> None:
    schema.pop("default", None)


def omittable() -> Any:
    """Declare an optional field that is omitted when absent, never null.

    The field is not required and a null value is rejected. Fields the contract
    explicitly allows to be null are declared required as ``T | None`` instead.
    """
    return Field(default=None, json_schema_extra=_drop_default)


class ContractModel(BaseModel):
    """A fully specified contract object: strict types, no unknown keys."""

    model_config = ConfigDict(strict=True, extra="forbid")

    @field_validator("*", mode="before")
    @classmethod
    def _omitted_never_null(cls, value: Any, info: ValidationInfo) -> Any:
        field = cls.model_fields.get(info.field_name or "")
        if value is None and field is not None and field.json_schema_extra is _drop_default:
            raise PydanticCustomError("omit_never_null", "must be omitted, never null")
        return value


class LooseSection(BaseModel):
    """A section not yet modelled field by field: any JSON object is accepted."""

    model_config = ConfigDict(strict=True, extra="allow")
