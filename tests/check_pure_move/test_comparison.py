"""The pure-move check's comparison rules, run in-process on base and head trees."""

from __future__ import annotations

from collections.abc import Callable

from tests.check_pure_move.trees import CALC, Tree

Compare = Callable[..., tuple[list[str], list[str]]]
Split = Callable[..., dict[str, str]]


def test_a_test_file_split_into_two_passes(head: Tree, split: Split, compare: Compare) -> None:
    head.split_tests(split())

    report, problems = compare()

    assert report[1] == "assertions: base 4, head 4 (0 missing, 0 added)"
    assert problems == []


def test_an_assertion_edited_during_the_move_fails_and_names_both_versions(
    head: Tree, split: Split, compare: Compare
) -> None:
    head.split_tests(split('parity(4) == "even"', 'parity(4) in ("even", "odd")'))

    report, problems = compare()

    assert "  added x1: assert parity(4) in ('even', 'odd')  [head tests/test_parity.py:6]" in report
    assert problems == ["missing assertion x1: assert parity(4) == 'even'  [base tests/test_calc.py:12]"]


def test_reformatting_an_assertion_is_not_an_edit(head: Tree, split: Split, compare: Compare) -> None:
    reformatted = "assert (\n        parity(3)  # odd\n        == 'odd'\n    )"
    head.split_tests(split('assert parity(3) == "odd"', reformatted))

    _, problems = compare()

    assert problems == []


def test_a_lost_pytest_raises_fails(head: Tree, split: Split, compare: Compare) -> None:
    files = split()
    files["tests/test_double.py"] = files["tests/test_double.py"].replace("TypeError", "Exception")
    head.split_tests(files)

    _, problems = compare()

    assert problems == ["missing assertion x1: pytest.raises(TypeError)  [base tests/test_calc.py:16]"]


def test_a_function_that_covers_fewer_lines_in_head_fails(compare: Compare) -> None:
    _, problems = compare(base_lines={"parity": 4}, head_lines={"parity": 1})

    assert problems == ["coverage dropped: parity [base src/calc.py:5]: 4 -> 1 covered lines"]


def test_a_source_module_split_with_a_re_export_passes(head: Tree, compare: Compare) -> None:
    double, _, parity = CALC.partition("\n\ndef parity")
    head.write("src/calc.py", "from calc_parity import parity\n\n__all__ = ['parity']\n\n\n" + double)
    head.write("src/calc_parity.py", "def parity" + parity)

    report, problems = compare(base_lines={"parity": 4}, head_lines={"parity": 4})

    assert report[2] == "src functions: base 2, head 2; covered lines in them: base 4, head 4"
    assert problems == []


def test_a_function_edited_during_a_source_split_fails(head: Tree, compare: Compare) -> None:
    double, _, parity = CALC.partition("\n\ndef parity")
    head.write("src/calc.py", "from calc_parity import parity\n\n\n" + double)
    head.write("src/calc_parity.py", "def parity" + parity.replace("x % 2", "x % 2 == 1"))

    _, problems = compare()

    assert problems == ["function changed, renamed or removed: parity [base src/calc.py:5]"]
