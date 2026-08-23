"""End-to-end acceptance tests: the optimizer must fill a full DraftKings roster.

These solve a representative slate for each sport through the real
``PulpCbcSolver`` and assert the one ground truth no design choice can change:
the lineup fills *exactly* the roster DraftKings requires, under the salary cap.

The roster model (ADR-0005): ``Sport.positions`` enumerates every slot with its
true multiplicity and is the sole source of truth; the solver fills one player
per listed slot, matching each against DraftKings' per-player ``roster_pos``.

Enabled sports (``allow_optimizer=True``) have layouts confirmed against real
standings files and must pass. Gated sports are marked ``xfail(strict=True)`` —
their ``positions`` is unconfirmed (or, for XFL/USFL, uses a compound ``WR/TE``
slot that ``roster_pos.split('/')`` would break), so they stay off until a real
salary file confirms them. When one is confirmed and enumerated, its xfail flips
to a hard failure, the signal to enable it and drop the marker.

Composition assertions (how many of each position, which slot label a flex
player receives) are deliberately *not* made here: only total size + cap
validity are the design-independent ground truth.
"""

from __future__ import annotations

import pytest

from dk_results.analytics.optimizer import Optimizer
from dk_results.domain.player import Player
from dk_results.domain.sport import (
    CFBSport,
    GolfSport,
    MLBSport,
    NBASport,
    NFLSport,
    NHLSport,
    SOCSport,
    Sport,
    USFLSport,
    WeekendGolfSport,
    XFLSport,
)


def _p(name: str, roster_pos: str, salary: int, fpts: float) -> Player:
    player = Player(
        name=name,
        pos="",
        roster_pos_raw=roster_pos,
        salary_raw=salary,
        game_info="Final",
        team_abbv="TM",
    )
    player.fpts = fpts
    return player


def _pool(prefix: str, roster_pos: str, count: int, base_salary: int) -> dict[str, Player]:
    """A pool of interchangeable players at one eligibility, descending in value."""
    return {f"{prefix}{i}": _p(f"{prefix}{i}", roster_pos, base_salary - i * 100, 20.0 - i) for i in range(count)}


def _nfl_slate() -> dict[str, Player]:
    slate: dict[str, Player] = {"QB0": _p("QB0", "QB", 6000, 25)}
    slate.update(_pool("RB", "RB/FLEX", 4, 6000))
    slate.update(_pool("WR", "WR/FLEX", 5, 6000))
    slate.update(_pool("TE", "TE/FLEX", 3, 4000))
    slate.update(_pool("DST", "DST", 2, 3000))
    return slate


def _nba_slate() -> dict[str, Player]:
    slate: dict[str, Player] = {}
    slate.update(_pool("PG", "PG/G/UTIL", 3, 6000))
    slate.update(_pool("SG", "SG/G/UTIL", 3, 5500))
    slate.update(_pool("SF", "SF/F/UTIL", 3, 5500))
    slate.update(_pool("PF", "PF/F/UTIL", 3, 5000))
    slate.update(_pool("C", "C/UTIL", 3, 5000))
    return slate


def _mlb_slate() -> dict[str, Player]:
    slate: dict[str, Player] = {}
    slate.update(_pool("P", "P", 4, 8000))
    for pos in ("C", "1B", "2B", "3B", "SS"):
        slate.update(_pool(pos, pos, 2, 4500))
    slate.update(_pool("OF", "OF", 6, 4500))
    return slate


def _soc_slate() -> dict[str, Player]:
    slate: dict[str, Player] = {}
    slate.update(_pool("F", "F/UTIL", 4, 5000))
    slate.update(_pool("M", "M/UTIL", 4, 4500))
    slate.update(_pool("D", "D/UTIL", 4, 4500))
    slate.update(_pool("GK", "GK", 2, 4000))
    return slate


def _cfb_slate() -> dict[str, Player]:
    slate: dict[str, Player] = {"QB0": _p("QB0", "QB/S-FLEX", 6000, 25)}
    slate.update(_pool("RB", "RB/FLEX/S-FLEX", 4, 5500))
    slate.update(_pool("WR", "WR/FLEX/S-FLEX", 6, 5500))
    return slate


def _golf_slate() -> dict[str, Player]:
    return _pool("G", "G", 10, 7000)


def _weekend_golf_slate() -> dict[str, Player]:
    return _pool("WG", "WG", 10, 7000)


def _nhl_slate() -> dict[str, Player]:
    slate: dict[str, Player] = {}
    slate.update(_pool("C", "C/UTIL", 4, 5000))
    slate.update(_pool("W", "W/UTIL", 5, 5000))
    slate.update(_pool("D", "D/UTIL", 4, 4500))
    slate.update(_pool("G", "G", 2, 4000))
    return slate


def _xfl_slate() -> dict[str, Player]:
    slate: dict[str, Player] = {"QB0": _p("QB0", "QB", 6000, 25)}
    slate.update(_pool("RB", "RB/FLEX", 3, 5000))
    slate.update(_pool("WR", "WR/FLEX", 4, 5000))
    slate.update(_pool("TE", "TE/FLEX", 3, 4000))
    slate.update(_pool("DST", "DST", 2, 3000))
    return slate


_GATED = "gated (#62): positions unconfirmed against a real file; enumerate + enable to flip this to XPASS"


@pytest.mark.parametrize(
    ("sport", "slate", "roster_size"),
    [
        # Enabled: layouts confirmed against real standings files.
        pytest.param(NFLSport, _nfl_slate(), 9, id="nfl"),
        pytest.param(NBASport, _nba_slate(), 8, id="nba"),
        pytest.param(MLBSport, _mlb_slate(), 10, id="mlb"),
        pytest.param(SOCSport, _soc_slate(), 8, id="soc"),
        pytest.param(CFBSport, _cfb_slate(), 8, id="cfb"),
        pytest.param(GolfSport, _golf_slate(), 6, id="golf"),
        pytest.param(WeekendGolfSport, _weekend_golf_slate(), 6, id="weekend_golf"),
        # Gated: positions not yet confirmed, so allow_optimizer stays False.
        pytest.param(NHLSport, _nhl_slate(), 9, id="nhl", marks=pytest.mark.xfail(reason=_GATED, strict=True)),
        pytest.param(XFLSport, _xfl_slate(), 7, id="xfl", marks=pytest.mark.xfail(reason=_GATED, strict=True)),
        pytest.param(USFLSport, _xfl_slate(), 7, id="usfl", marks=pytest.mark.xfail(reason=_GATED, strict=True)),
    ],
)
def test_optimizer_fills_full_roster(sport: type[Sport], slate: dict[str, Player], roster_size: int) -> None:
    lineup = Optimizer(sport, slate).get_optimal_lineup()

    assert lineup is not None, f"{sport.name}: solver returned no lineup"
    assert len(lineup) == roster_size, f"{sport.name}: expected {roster_size} players, got {len(lineup)}"
    total_salary = sum(sp.player.salary for sp in lineup)
    assert total_salary <= sport.salary_cap, f"{sport.name}: ${total_salary} over cap ${sport.salary_cap}"


def test_allow_optimizer_is_opt_in() -> None:
    # The base default is off; only confirmed sports turn it on (ADR-0005).
    assert Sport.allow_optimizer is False
    for enabled in (NFLSport, NBASport, MLBSport, SOCSport, CFBSport, GolfSport, WeekendGolfSport):
        assert enabled.allow_optimizer is True, f"{enabled.name} should be enabled"
    for gated in (NHLSport, XFLSport, USFLSport):
        assert gated.allow_optimizer is False, f"{gated.name} should be gated"
