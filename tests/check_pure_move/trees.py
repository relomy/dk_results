"""Base and head trees for the pure-move check tests: a calc module and its tests."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check-pure-move.py"

PYPROJECT = '[tool.pytest.ini_options]\ntestpaths = ["tests"]\npythonpath = ["src"]\n'

CALC = """\
def double(x):
    return x * 2


def parity(x):
    if x % 2:
        return "odd"
    return "even"
"""

TESTS = """\
import pytest

from calc import double, parity


def test_double():
    assert double(2) == 4


def test_parity():
    assert parity(3) == "odd"
    assert parity(4) == "even"


def test_double_rejects_none():
    with pytest.raises(TypeError):
        double(None)
"""

PARITY_TESTS = """\
def test_parity():
    assert parity(3) == "odd"
    assert parity(4) == "even"
"""

BASE_FILES = {"pyproject.toml": PYPROJECT, "src/calc.py": CALC, "tests/test_calc.py": TESTS}


class Tree:
    """A directory holding the base files; edit it to make a head."""

    def __init__(self, root: Path) -> None:
        self.root = root
        for path, content in BASE_FILES.items():
            self.write(path, content)

    def write(self, path: str, content: str) -> None:
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    def remove(self, path: str) -> None:
        (self.root / path).unlink()

    def split_tests(self, files: dict[str, str]) -> None:
        """Replace tests/test_calc.py with `files`."""
        self.remove("tests/test_calc.py")
        for path, content in files.items():
            self.write(path, content)


class Repo(Tree):
    """A git repo whose `main` branch is the base; edit the working tree, then check it."""

    def __init__(self, root: Path) -> None:
        super().__init__(root)
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.name", "Test")
        self.git("config", "user.email", "test@example.com")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "base")

    def git(self, *args: str) -> None:
        subprocess.run(["git", *args], cwd=self.root, check=True, capture_output=True)

    def check(self, base: str = "main") -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--base", base], cwd=self.root, capture_output=True, text=True
        )
