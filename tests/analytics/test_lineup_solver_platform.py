"""Platform-specific CBC selection for the PuLP adapter."""

import platform

import pulp as pl
import pytest

from dk_results.analytics import lineup_solver


@pytest.mark.parametrize(
    ("system", "machine", "expected"),
    [
        ("Darwin", "arm64", "native"),
        ("Darwin", "x86_64", "bundled"),
        ("Linux", "aarch64", "bundled"),
    ],
)
def test_cbc_solver_selects_platform_binary(
    monkeypatch: pytest.MonkeyPatch,
    system: str,
    machine: str,
    expected: str,
) -> None:
    monkeypatch.setattr(platform, "system", lambda: system)
    monkeypatch.setattr(platform, "machine", lambda: machine)
    constructed: list[str] = []

    class FakeSolver:
        def available(self) -> bool:
            return True

    def native_solver(*, msg: int) -> FakeSolver:
        assert msg == 0
        constructed.append("native")
        return FakeSolver()

    def bundled_solver(*, msg: int) -> FakeSolver:
        assert msg == 0
        constructed.append("bundled")
        return FakeSolver()

    monkeypatch.setattr(lineup_solver.pl, "COIN_CMD", native_solver)
    monkeypatch.setattr(lineup_solver.pl, "PULP_CBC_CMD", bundled_solver)

    solver = lineup_solver._cbc_solver()

    assert isinstance(solver, FakeSolver)
    assert constructed == [expected]


def test_cbc_solver_explains_missing_native_cbc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(platform, "system", lambda: "Darwin")
    monkeypatch.setattr(platform, "machine", lambda: "arm64")

    class MissingSolver:
        def available(self) -> bool:
            return False

    monkeypatch.setattr(lineup_solver.pl, "COIN_CMD", lambda *, msg: MissingSolver())

    with pytest.raises(pl.PulpSolverError, match="brew install cbc.*PATH"):
        lineup_solver._cbc_solver()
