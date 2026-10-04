"""Contract for the snapshot envelope: root model, contract check, JSON Schema."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Literal

from pydantic import StrictStr, ValidationError

from dk_results.services.snapshot_v3.models.base import ContractModel, LooseSection
from dk_results.services.snapshot_v3.models.contest import Contest
from dk_results.services.snapshot_v3.models.players import SportPlayer


class SelectionReason(LooseSection):
    """Why the primary contest was selected."""


class PrimaryContest(ContractModel):
    """The contest the sport payload is built around."""

    contest_id: StrictStr
    contest_key: StrictStr
    selection_reason: SelectionReason
    selected_at: StrictStr


class SportPayload(ContractModel):
    """One sport's slice of the snapshot."""

    status: Literal["ok", "stale", "error"]
    updated_at: StrictStr
    players: list[SportPlayer]
    primary_contest: PrimaryContest
    contests: list[Contest]


class SnapshotEnvelope(ContractModel):
    """A schema-3 live snapshot, keyed by lowercase sport name."""

    schema_version: Literal[3]
    snapshot_at: StrictStr
    generated_at: StrictStr
    sports: dict[str, SportPayload]


def _format_location(location: Sequence[int | str]) -> str:
    path = ""
    for part in location:
        path += f"[{part}]" if isinstance(part, int) else f".{part}"
    return path.lstrip(".")


def contract_violations(envelope: Any) -> list[str]:
    """Check an envelope against the contract; one ``"<path>: <reason>"`` per violation."""
    try:
        SnapshotEnvelope.model_validate(envelope)
    except ValidationError as exc:
        return [f"{_format_location(error['loc'])}: {error['msg']}" for error in exc.errors()]
    return []


def snapshot_json_schema() -> dict[str, Any]:
    """The contract as a JSON Schema document."""
    schema = SnapshotEnvelope.model_json_schema()
    return {"$schema": "https://json-schema.org/draft/2020-12/schema", **schema}
