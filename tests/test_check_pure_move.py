"""The pure-move check: the script's command line against a real throwaway git repo."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check-pure-move.py"

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


class Repo:
    """A git repo whose `main` branch is the base; edit the working tree, then check it."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.name", "Test")
        self.git("config", "user.email", "test@example.com")
        self.write("pyproject.toml", PYPROJECT)
        self.write("src/calc.py", CALC)
        self.write("tests/test_calc.py", TESTS)
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "base")

    def git(self, *args: str) -> None:
        subprocess.run(["git", *args], cwd=self.root, check=True, capture_output=True)

    def write(self, path: str, content: str) -> None:
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    def remove(self, path: str) -> None:
        (self.root / path).unlink()

    def check(self) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--base", "main"], cwd=self.root, capture_output=True, text=True
        )


@pytest.fixture
def repo(tmp_path: Path) -> Repo:
    return Repo(tmp_path)


def _split_tests(parity_tests: str) -> dict[str, str]:
    """TESTS split into two files, with `parity_tests` as the second file's body."""
    head, _, rest = TESTS.partition("def test_parity():")
    _, _, raises = rest.partition("def test_double_rejects_none():")
    return {
        "tests/test_double.py": head + "def test_double_rejects_none():" + raises,
        "tests/test_parity.py": "from calc import parity\n\n\n" + parity_tests,
    }


PARITY_TESTS = """\
def test_parity():
    assert parity(3) == "odd"
    assert parity(4) == "even"
"""


def _apply(repo: Repo, files: dict[str, str]) -> None:
    repo.remove("tests/test_calc.py")
    for path, content in files.items():
        repo.write(path, content)


def test_a_test_file_split_into_two_passes(repo: Repo) -> None:
    _apply(repo, _split_tests(PARITY_TESTS))

    result = repo.check()

    assert result.returncode == 0, result.stderr
    assert "tests collected: base 3, head 3" in result.stdout
    assert "assertions: base 4, head 4" in result.stdout


def test_an_assertion_edited_during_the_move_fails_and_names_both_versions(repo: Repo) -> None:
    _apply(repo, _split_tests(PARITY_TESTS.replace('parity(4) == "even"', 'parity(4) in ("even", "odd")')))

    result = repo.check()

    assert result.returncode == 1
    assert "missing assertion x1: assert parity(4) == 'even'  [base tests/test_calc.py:12]" in result.stderr
    assert "added x1: assert parity(4) in ('even', 'odd')  [head tests/test_parity.py:6]" in result.stdout
    assert "Not a pure move" in result.stderr


def test_reformatting_an_assertion_is_not_an_edit(repo: Repo) -> None:
    reformatted = PARITY_TESTS.replace(
        'assert parity(3) == "odd"', "assert (\n        parity(3)  # odd\n        == 'odd'\n    )"
    )
    _apply(repo, _split_tests(reformatted))

    assert repo.check().returncode == 0


def test_a_lost_pytest_raises_fails(repo: Repo) -> None:
    files = _split_tests(PARITY_TESTS)
    files["tests/test_double.py"] = files["tests/test_double.py"].replace("TypeError", "Exception")
    _apply(repo, files)

    result = repo.check()

    assert result.returncode == 1
    assert "missing assertion x1: pytest.raises(TypeError)" in result.stderr


def test_a_test_dropped_from_collection_fails(repo: Repo) -> None:
    files = _split_tests(PARITY_TESTS)
    files["tests/parity_checks.py"] = files.pop("tests/test_parity.py")
    _apply(repo, files)

    result = repo.check()

    assert result.returncode == 1
    assert "tests collected: base 3, head 2" in result.stdout
    assert "head collects 1 fewer tests than base" in result.stderr


def test_an_unknown_base_ref_cannot_run(repo: Repo) -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--base", "no-such-ref"], cwd=repo.root, capture_output=True, text=True
    )

    assert result.returncode == 2
    assert "cannot read no-such-ref" in result.stderr


def test_a_moved_test_that_no_longer_runs_fails_on_the_coverage_it_dropped(repo: Repo) -> None:
    skipped = "import pytest\n\nfrom calc import parity\n\n\n@pytest.mark.skip\n" + PARITY_TESTS
    files = _split_tests(PARITY_TESTS)
    files["tests/test_parity.py"] = skipped
    _apply(repo, files)

    result = repo.check()

    assert result.returncode == 1
    assert "coverage dropped: parity [base src/calc.py:5]: 4 -> 1 covered lines" in result.stderr


def test_a_source_module_split_with_a_re_export_passes(repo: Repo) -> None:
    double, _, parity = CALC.partition("\n\ndef parity")
    repo.write("src/calc.py", "from calc_parity import parity\n\n__all__ = ['parity']\n\n\n" + double)
    repo.write("src/calc_parity.py", "def parity" + parity)

    result = repo.check()

    assert result.returncode == 0, result.stderr
    assert "src functions: base 2, head 2" in result.stdout


def test_a_function_edited_during_a_source_split_fails(repo: Repo) -> None:
    double, _, parity = CALC.partition("\n\ndef parity")
    repo.write("src/calc.py", "from calc_parity import parity\n\n\n" + double)
    repo.write("src/calc_parity.py", "def parity" + parity.replace("x % 2", "x % 2 == 1"))

    result = repo.check()

    assert result.returncode == 1
    assert "function changed, renamed or removed: parity [base src/calc.py:5]" in result.stderr


def test_a_moved_test_that_now_fails_is_reported_with_the_assertion_diff(repo: Repo) -> None:
    _apply(repo, _split_tests(PARITY_TESTS.replace('parity(4) == "even"', 'parity(4) == "odd"')))

    result = repo.check()

    assert result.returncode == 1
    assert "missing assertion x1: assert parity(4) == 'even'" in result.stderr
    assert "tests fail in head: tests/test_parity.py::test_parity" in result.stderr
