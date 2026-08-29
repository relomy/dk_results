"""Compare Radon complexity for Python blocks changed by a pull request."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Violation:
    name: str
    message: str


def flatten_blocks(module: str, radon_blocks: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Return Radon blocks keyed by qualified module/class/function name."""
    flattened: dict[str, dict[str, Any]] = {}
    for block in radon_blocks:
        name = _qualified_name(module, block)
        flattened[name] = block
        for method in block.get("methods", []):
            method_name = _qualified_name(name, method, include_class=False)
            flattened[method_name] = method
    return flattened


def compare_blocks(base_blocks: dict[str, dict[str, Any]], head_blocks: dict[str, dict[str, Any]]) -> list[Violation]:
    """Find new blocks worse than B and complexity increases in existing blocks."""
    violations: list[Violation] = []
    for name, head in sorted(head_blocks.items()):
        head_complexity = int(head["complexity"])
        head_rank = str(head["rank"])
        base = base_blocks.get(name)
        if base is None:
            if head_complexity > 10:
                violations.append(
                    Violation(
                        name,
                        f"{name} is grade {head_rank} (complexity {head_complexity}); "
                        "new blocks must be grade B or better",
                    )
                )
            continue
        base_complexity = int(base["complexity"])
        if head_complexity > base_complexity:
            violations.append(
                Violation(
                    name,
                    f"{name} increased from {base['rank']}{base_complexity} to {head_rank}{head_complexity}",
                )
            )
    return violations


def _qualified_name(parent: str, block: dict[str, Any], *, include_class: bool = True) -> str:
    name = str(block["name"])
    if include_class and block.get("type") == "method" and block.get("classname"):
        name = f"{block['classname']}.{name}"
    return f"{parent}.{name}"


def _module_name(path: str) -> str:
    module = Path(path).with_suffix("").as_posix().replace("/", ".")
    return module.removeprefix("src.")


def _git(*args: str) -> str:
    result = subprocess.run(["git", *args], check=True, capture_output=True, text=True)
    return result.stdout


def _changed_python_files(base: str, head: str) -> list[str]:
    output = _git("diff", "--name-only", "--diff-filter=ACMR", base, head, "--", "*.py")
    return [line for line in output.splitlines() if line]


def _materialize(revision: str, relative_path: str, directory: Path) -> Path | None:
    destination = directory / relative_path
    try:
        content = _git("show", f"{revision}:{relative_path}")
    except subprocess.CalledProcessError:
        return None
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(content)
    return destination


def _radon(path: Path, module: str) -> dict[str, dict[str, Any]]:
    result = subprocess.run(
        [sys.executable, "-m", "radon", "cc", "--json", str(path)],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)
    return flatten_blocks(module, next(iter(payload.values()), []))


def check_revisions(base: str, head: str) -> list[Violation]:
    changed_files = _changed_python_files(base, head)
    violations: list[Violation] = []
    with tempfile.TemporaryDirectory(prefix="complexity-ratchet-") as temporary_directory:
        root = Path(temporary_directory)
        for relative_path in changed_files:
            module = _module_name(relative_path)
            base_path = _materialize(base, relative_path, root / "base")
            head_path = _materialize(head, relative_path, root / "head")
            base_blocks = _radon(base_path, module) if base_path else {}
            head_blocks = _radon(head_path, module) if head_path else {}
            violations.extend(compare_blocks(base_blocks, head_blocks))
    return violations


def main() -> int:
    base = sys.argv[1] if len(sys.argv) > 1 else _git("merge-base", "origin/main", "HEAD").strip()
    head = sys.argv[2] if len(sys.argv) > 2 else "HEAD"
    violations = check_revisions(base, head)
    for violation in violations:
        print(f"::error::{violation.message}")
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
