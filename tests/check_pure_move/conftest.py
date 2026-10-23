"""Fixtures for the pure-move check tests.

Every check through the script's command line costs two pytest runs, so
`test_command_line.py` covers only what needs them: the test count, the
coverage run, failing tests and the exit codes. The comparison rules
(assertions moved, functions unchanged, coverage kept) run in-process in
`test_comparison.py` on a base and a head tree written to disk.
"""

from __future__ import annotations

import importlib.util
import sys
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from types import ModuleType

import pytest

from tests.check_pure_move.trees import PARITY_TESTS, SCRIPT, TESTS, Repo, Tree


@pytest.fixture
def repo(tmp_path: Path) -> Repo:
    return Repo(tmp_path)


@pytest.fixture
def base(tmp_path: Path) -> Tree:
    return Tree(tmp_path / "base")


@pytest.fixture
def head(tmp_path: Path) -> Tree:
    return Tree(tmp_path / "head")


@pytest.fixture
def split() -> Callable[..., dict[str, str]]:
    """TESTS split into two files, the second holding PARITY_TESTS with `old` replaced by `new`."""

    def build(old: str = "", new: str = "") -> dict[str, str]:
        head, _, rest = TESTS.partition("def test_parity():")
        _, _, raises = rest.partition("def test_double_rejects_none():")
        return {
            "tests/test_double.py": head + "def test_double_rejects_none():" + raises,
            "tests/test_parity.py": "from calc import parity\n\n\n" + PARITY_TESTS.replace(old, new),
        }

    return build


@pytest.fixture(scope="session")
def pure_move() -> ModuleType:
    """The script, imported so its comparison runs in-process."""
    spec = importlib.util.spec_from_file_location("check_pure_move", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses resolve annotations through sys.modules
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def compare(pure_move: ModuleType, base: Tree, head: Tree) -> Callable[..., tuple[list[str], list[str]]]:
    """The script's (report, problems) for `base` against `head`, without running pytest.

    Each tree measures 0 tests and no failures; its src functions cover the lines
    given by name in `base_lines` and `head_lines`, else none.
    """

    def measure(tree: Tree, lines: dict[str, int]) -> object:
        found, assertion_at = pure_move._assertions(tree.root)
        covered: Counter[str] = Counter()
        function_at: dict[str, str] = {}
        for path in pure_move._python_files(tree.root, "src"):
            rel = path.relative_to(tree.root).as_posix()
            for start, _, key in pure_move._functions(pure_move._parse(tree.root, path)):
                covered[key] += lines.get(key.partition("#")[0], 0)
                function_at[key] = f"{rel}:{start}"
        return pure_move.Measurement(0, found, assertion_at, covered, function_at, [])

    def run(
        base_lines: dict[str, int] | None = None, head_lines: dict[str, int] | None = None
    ) -> tuple[list[str], list[str]]:
        return pure_move._compare(measure(base, base_lines or {}), measure(head, head_lines or {}))

    return run
