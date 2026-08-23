"""Typed schema-3 snapshot contract records and boundary validation."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class DashboardContest:
    """The single published contest for a sport snapshot."""

    contest_id: str
    contest_key: str
    name: str
    sport: str
    contest_type: str
    start_time: str
    state: str
    entry_fee_cents: int
    prize_pool_cents: int
    currency: str
    max_entries: int
    extras: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.extras,
            "contest_id": self.contest_id,
            "contest_key": self.contest_key,
            "name": self.name,
            "sport": self.sport,
            "contest_type": self.contest_type,
            "start_time": self.start_time,
            "state": self.state,
            "entry_fee_cents": self.entry_fee_cents,
            "prize_pool_cents": self.prize_pool_cents,
            "currency": self.currency,
            "max_entries": self.max_entries,
        }


@dataclass(frozen=True)
class DashboardEnvelope:
    """Schema-3 multi-sport envelope with deterministic serialization inputs."""

    snapshot_at: str
    generated_at: str
    sports: dict[str, dict[str, Any]]
    schema_version: int = 3

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "snapshot_at": self.snapshot_at,
            "generated_at": self.generated_at,
            "sports": {key: self.sports[key] for key in sorted(self.sports)},
        }


@dataclass(frozen=True)
class CollectedSnapshot(Mapping[str, Any]):
    """Typed boundary record for the source sections of one contest."""

    sport: str
    contest: dict[str, Any]
    standings: tuple[dict[str, Any], ...]
    players: tuple[dict[str, Any], ...]
    vip_lineups: tuple[dict[str, Any], ...]
    train_clusters: tuple[dict[str, Any], ...]
    ownership: dict[str, Any]
    cash_line: dict[str, Any]
    extras: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        core = {
            "sport": self.sport,
            "contest": dict(self.contest),
            "standings": [dict(row) for row in self.standings],
            "players": [dict(row) for row in self.players],
            "vip_lineups": [dict(row) for row in self.vip_lineups],
            "train_clusters": [dict(row) for row in self.train_clusters],
            "ownership": dict(self.ownership),
            "cash_line": dict(self.cash_line),
        }
        return {**self.extras, **core}

    def __getitem__(self, key: str) -> Any:
        return self.to_dict()[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self.to_dict())

    def __len__(self) -> int:
        return len(self.to_dict())


@dataclass(frozen=True)
class DerivedSnapshot:
    """Typed analytics result derived from a collected contest."""

    distance_to_cash: dict[str, Any] | None = None
    threat: dict[str, Any] | None = None
    avg_salary_per_player_remaining: float | None = None


def collected_snapshot_from_mapping(snapshot: dict[str, Any]) -> CollectedSnapshot:
    """Convert the collector's mapping at the analytics seam."""

    def rows(key: str) -> tuple[dict[str, Any], ...]:
        return tuple(row for row in snapshot.get(key, []) if isinstance(row, dict))

    return CollectedSnapshot(
        sport=str(snapshot.get("sport") or ""),
        contest=dict(snapshot.get("contest") or {}),
        standings=rows("standings"),
        players=rows("players"),
        vip_lineups=rows("vip_lineups"),
        train_clusters=rows("train_clusters"),
        ownership=dict(snapshot.get("ownership") or {}),
        cash_line=dict(snapshot.get("cash_line") or {}),
        extras={
            key: value
            for key, value in snapshot.items()
            if key
            not in {
                "sport",
                "contest",
                "standings",
                "players",
                "vip_lineups",
                "train_clusters",
                "ownership",
                "cash_line",
            }
        },
    )


def validate_v3_envelope(payload: dict[str, Any]) -> list[str]:
    """Return contract violations without mutating the candidate payload."""

    violations: list[str] = []
    if payload.get("schema_version") != 3:
        violations.append("schema_version must equal 3")
    for field in ("snapshot_at", "generated_at"):
        value = payload.get(field)
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if parsed.tzinfo is None or parsed.astimezone(timezone.utc) != parsed:
                violations.append(f"{field} must be UTC")
        except (TypeError, ValueError):
            violations.append(f"{field} must be a valid RFC3339 timestamp")
    sports = payload.get("sports")
    if not isinstance(sports, dict) or not sports:
        return [*violations, "sports must contain at least one sport"]
    seen_keys: set[str] = set()
    for sport, value in sports.items():
        contests = value.get("contests") if isinstance(value, dict) else None
        if not isinstance(contests, list):
            violations.append(f"sports.{sport}.contests must contain exactly one contest")
            continue
        if len(contests) != 1:
            violations.append(f"sports.{sport}.contests must contain exactly one contest")
            if not contests:
                continue
        contest = contests[0]
        if not isinstance(contest, dict):
            violations.append(f"sports.{sport}.contests[0] must be an object")
            continue
        key = str(contest.get("contest_key") or "")
        if not key:
            violations.append(f"sports.{sport}.contests[0].contest_key is required")
        elif key in seen_keys:
            violations.append(f"contest_key collision: {key}")
        seen_keys.add(key)
        if contest.get("sport") != str(sport):
            violations.append(f"sports.{sport}.contests[0].sport must match sport key")
        if key and not key.startswith(f"{sport}:"):
            violations.append(f"sports.{sport}.contests[0].contest_key must match sport key")
    return violations
