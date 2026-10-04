"""Shared building blocks for the snapshot contract models."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ContractModel(BaseModel):
    """A fully specified contract object: strict types, no unknown keys."""

    model_config = ConfigDict(strict=True, extra="forbid")


class LooseSection(BaseModel):
    """A section not yet modelled field by field: any JSON object is accepted."""

    model_config = ConfigDict(strict=True, extra="allow")


def _drop_default(schema: dict[str, Any]) -> None:
    schema.pop("default", None)


def omittable() -> Any:
    """Declare an optional field that is omitted when absent, never null.

    The field is not required and its type does not admit null, so a null value
    is rejected. Fields the contract explicitly allows to be null are declared
    as ``T | None`` instead.
    """
    return Field(default=None, json_schema_extra=_drop_default)
