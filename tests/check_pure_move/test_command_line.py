"""The pure-move check: the script's command line against a real throwaway git repo."""

from __future__ import annotations

from collections.abc import Callable

from tests.check_pure_move.trees import Repo


def test_a_test_file_split_into_two_passes(repo: Repo, split: Callable[..., dict[str, str]]) -> None:
    repo.split_tests(split())

    result = repo.check()

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        "pure-move check: working tree vs main",
        "tests collected: base 3, head 3",
        "assertions: base 4, head 4 (0 missing, 0 added)",
        "src functions: base 2, head 2; covered lines in them: base 6, head 6",
        "OK: pure move",
    ]


def test_a_test_dropped_from_collection_fails(repo: Repo, split: Callable[..., dict[str, str]]) -> None:
    files = split()
    files["tests/parity_checks.py"] = files.pop("tests/test_parity.py")
    repo.split_tests(files)

    result = repo.check()

    assert result.returncode == 1
    assert "tests collected: base 3, head 2" in result.stdout
    assert "head collects 1 fewer tests than base" in result.stderr
    assert "coverage dropped: parity [base src/calc.py:5]: 4 -> 1 covered lines" in result.stderr


def test_a_moved_test_that_now_fails_is_reported_with_the_assertion_diff(
    repo: Repo, split: Callable[..., dict[str, str]]
) -> None:
    repo.split_tests(split('parity(4) == "even"', 'parity(4) == "odd"'))

    result = repo.check()

    assert result.returncode == 1
    assert "missing assertion x1: assert parity(4) == 'even'" in result.stderr
    assert "tests fail in head: tests/test_parity.py::test_parity" in result.stderr


def test_an_unknown_base_ref_cannot_run(repo: Repo) -> None:
    result = repo.check("no-such-ref")

    assert result.returncode == 2
    assert "cannot read no-such-ref" in result.stderr
