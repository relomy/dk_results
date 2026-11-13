"""Fixtures for the snapshot_v3 collector tests: edge stubs and Player / standings-user builders."""

from collections.abc import Callable
from types import SimpleNamespace

import pytest

from dk_results.domain.player import Player
from tests.services.collector_edges import _FakeContestDB, _FakeDK


@pytest.fixture
def make_dk() -> type[_FakeDK]:
    """``make_dk(**options)``: a DraftKings edge stub."""
    return _FakeDK


@pytest.fixture
def make_contest_db() -> type[_FakeContestDB]:
    """``make_contest_db(**options)``: an in-memory ContestDatabase edge stub."""
    return _FakeContestDB


@pytest.fixture
def salary_player() -> Callable[[str, str, str, str | None], Player]:
    def build(name: str, team: str, game_info: str, draftable_id: str | None) -> Player:
        """A Player as the salary CSV + standings parse would leave it (sheet matchup_info included)."""
        player = Player(name, "QB", "QB/FLEX", 8000, game_info, team, draftable_id=draftable_id)
        player.update_stats("QB", "12.5%", "20.0")
        return player

    return build


@pytest.fixture
def by_name() -> Callable[[list[dict]], dict[str, dict]]:
    def index(rows: list[dict]) -> dict[str, dict]:
        return {row["name"]: row for row in rows}

    return index


@pytest.fixture
def field_user() -> Callable[..., SimpleNamespace]:
    def build(
        rank: int, entry_key: str, ownership: float | None, *, game_info: str = "Live", salary: int | None = None
    ) -> SimpleNamespace:
        lineupobj = (
            None
            if ownership is None
            else SimpleNamespace(lineup=[SimpleNamespace(game_info=game_info, ownership=ownership, salary=salary)])
        )
        return SimpleNamespace(
            rank=str(rank), pts="10", pmr="0", player_id=entry_key, name=f"u{entry_key}", salary=0, lineupobj=lineupobj
        )

    return build
