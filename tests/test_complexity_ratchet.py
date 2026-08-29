from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_MODULE_PATH = Path(__file__).parents[1] / ".github" / "complexity_ratchet.py"
_SPEC = importlib.util.spec_from_file_location("complexity_ratchet", _MODULE_PATH)
assert _SPEC is not None and _SPEC.loader is not None
complexity_ratchet = importlib.util.module_from_spec(_SPEC)
sys.modules["complexity_ratchet"] = complexity_ratchet
_SPEC.loader.exec_module(complexity_ratchet)


def test_new_block_above_b_grade_fails() -> None:
    violations = complexity_ratchet.compare_blocks({}, {"new_function": {"complexity": 11, "rank": "C"}})

    assert [violation.message for violation in violations] == [
        "new_function is grade C (complexity 11); new blocks must be grade B or better"
    ]


def test_existing_block_complexity_increase_fails() -> None:
    violations = complexity_ratchet.compare_blocks(
        {"module.function": {"complexity": 6, "rank": "B"}},
        {"module.function": {"complexity": 8, "rank": "B"}},
    )

    assert [violation.message for violation in violations] == [
        "module.function increased from B8 to B8".replace("B8", "B6", 1)
    ]


def test_improved_existing_block_passes() -> None:
    assert (
        complexity_ratchet.compare_blocks(
            {"function": {"complexity": 11, "rank": "C"}},
            {"function": {"complexity": 8, "rank": "B"}},
        )
        == []
    )


def test_unrelated_changes_with_unchanged_complexity_pass() -> None:
    assert (
        complexity_ratchet.compare_blocks(
            {"function": {"complexity": 8, "rank": "B"}},
            {"function": {"complexity": 8, "rank": "B"}},
        )
        == []
    )


def test_flattening_matches_methods_and_nested_blocks_by_qualified_name() -> None:
    blocks = complexity_ratchet.flatten_blocks(
        "package.module",
        [
            {
                "type": "class",
                "name": "Outer",
                "complexity": 3,
                "rank": "A",
                "methods": [
                    {
                        "type": "method",
                        "name": "method",
                        "classname": "Outer",
                        "complexity": 7,
                        "rank": "B",
                    }
                ],
            },
            {
                "type": "function",
                "name": "function",
                "complexity": 2,
                "rank": "A",
            },
        ],
    )

    assert set(blocks) == {"package.module.Outer", "package.module.Outer.method", "package.module.function"}
