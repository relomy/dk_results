"""Scalar types shared by the metrics contract models."""

from __future__ import annotations

from typing import Annotated

from pydantic import Field, Strict, StrictStr, StringConstraints

FiniteFloat = Annotated[float, Strict(), Field(allow_inf_nan=False)]
"""A JSON number: an int or float, never a bool or string, never NaN or infinite."""

NonNegativeFloat = Annotated[float, Strict(), Field(allow_inf_nan=False, ge=0)]

NonEmptyStr = Annotated[StrictStr, StringConstraints(min_length=1)]
