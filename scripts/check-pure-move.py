#!/usr/bin/env python3
"""Pure-move check: show that a token budget split moved code without changing behaviour.

Usage: uv run scripts/check-pure-move.py [--base REF]    (REF defaults to origin/main)

Compares the working tree (head) with REF (base), whose tree is extracted with
`git archive` into a temporary directory. Both run on this venv.

  tests       pytest's collected test count (from the coverage run): head must not be lower.
  assertions  every assertion in tests/, normalised with ast.unparse so layout and
              comments don't matter: head must still hold each base assertion
              (moved, not edited). Added assertions are listed but allowed.
  coverage    covered src/ lines per function, from one pytest-cov run of each tree.
              A function is identified by its qualified name plus a hash of its AST
              without line numbers, so it is the same function wherever it moves to.
              Each base function must exist unchanged in head and keep at least as
              many covered lines. Module and class body lines are not compared:
              a split rewrites imports, and they run on import anyway.
  failures    a failing test in either tree is listed as a regression.

Exit 0 when nothing regressed, 1 when something did, 2 when the check could not run
(unknown ref, a test file that doesn't parse, a pytest collection or usage error).
See docs/WORKFLOW.md#token-budget.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import tarfile
import tempfile
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree

# Calls that assert: pytest.raises(...), approx(...), mock.assert_called_once_with(...).
ASSERTING_CALLS = {"raises", "warns", "approx", "deprecated_call"}


class CheckError(Exception):
    """The check could not run; see the exit codes in the module docstring."""


@dataclass
class Measurement:
    tests: int
    assertions: Counter[str]
    assertion_at: dict[str, list[str]]
    covered: Counter[str]
    function_at: dict[str, str]
    failing: list[str]


def _run(args: list[str], cwd: Path, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, env=env, capture_output=True, text=True)


def _extract(ref: str, root: Path, dest: Path) -> None:
    archive = subprocess.run(["git", "archive", "--format=tar", ref], cwd=root, capture_output=True)
    if archive.returncode != 0:
        raise CheckError(f"cannot read {ref}: {archive.stderr.decode().strip()}")
    with tarfile.open(fileobj=io.BytesIO(archive.stdout)) as tar:
        tar.extractall(dest, filter="data")


def _pytest_env() -> dict[str, str]:
    """This environment without an enclosing pytest or coverage run's variables."""
    return {k: v for k, v in os.environ.items() if not k.startswith(("COV_CORE_", "COVERAGE_", "PYTEST_"))}


def _pytest(tree: Path, args: list[str], env: dict[str, str], exit_ok: tuple[int, ...] = (0,)) -> str:
    result = _run([sys.executable, "-m", "pytest", "-p", "no:cacheprovider", *args], tree, env)
    if result.returncode not in exit_ok:
        tail = "\n".join((result.stdout + result.stderr).splitlines()[-15:])
        raise CheckError(f"pytest {' '.join(args)} failed in {tree}:\n{tail}")
    return result.stdout


def _python_files(tree: Path, top: str) -> list[Path]:
    return sorted(p for p in (tree / top).rglob("*.py") if "__pycache__" not in p.parts)


def _parse(tree: Path, path: Path) -> ast.Module:
    rel = path.relative_to(tree).as_posix()
    try:
        return ast.parse(path.read_text(encoding="utf-8"), rel)
    except SyntaxError as exc:
        raise CheckError(f"cannot parse {rel}: {exc}") from exc


def _is_asserting_call(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    name = func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else ""
    return name in ASSERTING_CALLS or name.startswith("assert_")


def _assertions(tree: Path) -> tuple[Counter[str], dict[str, list[str]]]:
    found: Counter[str] = Counter()
    where: dict[str, list[str]] = {}
    for path in _python_files(tree, "tests"):
        rel = path.relative_to(tree).as_posix()
        for node in ast.walk(_parse(tree, path)):
            if isinstance(node, ast.Assert) or _is_asserting_call(node):
                text = ast.unparse(node)
                found[text] += 1
                where.setdefault(text, []).append(f"{rel}:{getattr(node, 'lineno', 0)}")
    return found, where


def _functions(node: ast.AST, prefix: str = "") -> list[tuple[int, int, str]]:
    """(first line, last line, key) of every function under `node`, nested ones included."""
    found = []
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            name = prefix + child.name
            digest = hashlib.sha256(ast.dump(child).encode()).hexdigest()[:12]
            found.append((child.lineno, child.end_lineno or child.lineno, f"{name}#{digest}"))
            found += _functions(child, name + ".<locals>.")
        elif isinstance(child, ast.ClassDef):
            found += _functions(child, prefix + child.name + ".")
        else:
            found += _functions(child, prefix)
    return found


def _tests_run(junit: Path) -> int:
    return sum(int(suite.get("tests", "0")) for suite in ElementTree.parse(junit).getroot().iter("testsuite"))


def _coverage(tree: Path, env: dict[str, str], workdir: Path) -> tuple[int, Counter[str], dict[str, str], list[str]]:
    """Tests run, covered lines per function key, where each function is, and the failing tests."""
    report = workdir / "coverage.json"
    junit = workdir / "junit.xml"
    env = {**env, "COVERAGE_FILE": str(workdir / ".coverage")}
    # Exit 1 is failing tests: still a coverage report, and the failures are a finding.
    # A collection error exits 2, so the junit count is every collected test.
    args = ["-q", "--cov=src", f"--cov-report=json:{report}", f"--junitxml={junit}"]
    out = _pytest(tree, args, env, exit_ok=(0, 1))
    failing = re.findall(r"^(?:FAILED|ERROR) (\S+)", out, re.MULTILINE)
    covered: Counter[str] = Counter()
    where: dict[str, str] = {}
    for rel, data in json.loads(report.read_text(encoding="utf-8"))["files"].items():
        spans = _functions(_parse(tree, tree / rel))
        for start, _, key in spans:
            covered[key] += 0
            where.setdefault(key, f"{Path(rel).as_posix()}:{start}")
        for line in data["executed_lines"]:
            owners = [(start, key) for start, end, key in spans if start <= line <= end]
            if owners:
                covered[max(owners)[1]] += 1
    return _tests_run(junit), covered, where, failing


def _measure(tree: Path, workdir: Path) -> Measurement:
    env = _pytest_env()
    workdir.mkdir()
    found, where = _assertions(tree)
    tests, covered, function_at, failing = _coverage(tree, env, workdir)
    return Measurement(tests, found, where, covered, function_at, failing)


def _short(text: str, limit: int = 160) -> str:
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _compare(base: Measurement, head: Measurement) -> tuple[list[str], list[str]]:
    """(report lines, problems)."""
    report = [f"tests collected: base {base.tests}, head {head.tests}"]
    problems = []
    if head.tests < base.tests:
        problems.append(f"head collects {base.tests - head.tests} fewer tests than base")
    missing = base.assertions - head.assertions
    added = head.assertions - base.assertions
    report.append(
        f"assertions: base {base.assertions.total()}, head {head.assertions.total()}"
        f" ({missing.total()} missing, {added.total()} added)"
    )
    for text, count in sorted(missing.items()):
        at = ", ".join(base.assertion_at[text])
        problems.append(f"missing assertion x{count}: {_short(text)}  [base {at}]")
    for text, count in sorted(added.items()):
        report.append(f"  added x{count}: {_short(text)}  [head {', '.join(head.assertion_at[text])}]")
    for label, run in (("base", base), ("head", head)):
        problems += [f"tests fail in {label}: {test}" for test in run.failing]
    report.append(_coverage_summary(base, head))
    problems += _coverage_problems(base, head)
    return report, problems


def _coverage_summary(base: Measurement, head: Measurement) -> str:
    return (
        f"src functions: base {len(base.covered)}, head {len(head.covered)};"
        f" covered lines in them: base {base.covered.total()}, head {head.covered.total()}"
    )


def _coverage_problems(base: Measurement, head: Measurement) -> list[str]:
    problems = []
    for key, lines in sorted(base.covered.items()):
        name = f"{key.partition('#')[0]} [base {base.function_at[key]}]"
        if key not in head.covered:
            problems.append(f"function changed, renamed or removed: {name}")
        elif head.covered[key] < lines:
            problems.append(f"coverage dropped: {name}: {lines} -> {head.covered[key]} covered lines")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base", default="origin/main", help="git ref to compare against (default: origin/main)")
    args = parser.parse_args(argv)
    try:
        top = _run(["git", "rev-parse", "--show-toplevel"], Path.cwd())
        if top.returncode != 0:
            raise CheckError("not inside a git repository")
        root = Path(top.stdout.strip())
        with tempfile.TemporaryDirectory(prefix="pure-move-") as tmp:
            base_tree = Path(tmp) / "base"
            _extract(args.base, root, base_tree)
            # The trees share nothing, so both pytest runs go at once.
            with ThreadPoolExecutor(2) as pool:
                base_run = pool.submit(_measure, base_tree, Path(tmp) / "base-run")
                head_run = pool.submit(_measure, root, Path(tmp) / "head-run")
                base, head = base_run.result(), head_run.result()
    except CheckError as exc:
        print(f"pure-move check could not run: {exc}", file=sys.stderr)
        return 2
    report, problems = _compare(base, head)
    print(f"pure-move check: working tree vs {args.base}")
    print("\n".join(report))
    if problems:
        print("\n".join(problems), file=sys.stderr)
        print("Not a pure move. See docs/WORKFLOW.md#token-budget", file=sys.stderr)
        return 1
    print("OK: pure move")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
