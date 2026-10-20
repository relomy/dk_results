"""The token budget check: the script's command line against a real throwaway git repo."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check-token-budget.sh"
LIMIT_BYTES = 20_000


class Repo:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.git("init", "-q")
        self.git("config", "user.name", "Test")
        self.git("config", "user.email", "test@example.com")

    def git(self, *args: str) -> None:
        subprocess.run(["git", *args], cwd=self.root, check=True, capture_output=True)

    def write(self, path: str, content: str | bytes) -> None:
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            target.write_bytes(content)
        else:
            target.write_text(content, encoding="utf-8")

    def stage(self, path: str, content: str | bytes) -> None:
        self.write(path, content)
        self.git("add", "--", path)

    def commit(self) -> None:
        self.git("commit", "-q", "-m", "seed")

    def check(self, *paths: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(["sh", str(SCRIPT), *paths], cwd=self.root, capture_output=True, text=True)


@pytest.fixture
def repo(tmp_path: Path) -> Repo:
    return Repo(tmp_path)


def test_oversized_staged_file_fails_with_its_tokens_budget_and_overage(repo: Repo) -> None:
    repo.stage("pkg/big.py", "x" * 20_400)

    result = repo.check()

    assert result.returncode == 1
    assert "pkg/big.py" in result.stderr
    assert "5100 tokens" in result.stderr
    assert "budget 5000" in result.stderr
    assert "over by 100" in result.stderr


def test_file_of_exactly_the_budget_passes(repo: Repo) -> None:
    repo.stage("pkg/edge.py", "x" * LIMIT_BYTES)

    assert repo.check().returncode == 0


def test_measures_the_staged_content_not_the_working_copy(repo: Repo) -> None:
    repo.stage("small_staged.py", "x" * 100)
    repo.write("small_staged.py", "x" * 30_000)
    repo.stage("big_staged.py", "x" * 30_000)
    repo.write("big_staged.py", "x" * 100)

    result = repo.check()

    assert result.returncode == 1
    assert "big_staged.py" in result.stderr
    assert "small_staged.py" not in result.stderr


def test_handles_paths_with_spaces(repo: Repo) -> None:
    repo.stage("my docs/big notes.md", "x" * 30_000)

    result = repo.check()

    assert result.returncode == 1
    assert "my docs/big notes.md: 7500 tokens" in result.stderr


def test_path_arguments_replace_the_staged_set(repo: Repo) -> None:
    repo.stage("committed big.py", "x" * 30_000)
    repo.commit()
    repo.stage("staged_big.py", "x" * 30_000)

    result = repo.check("committed big.py")

    assert result.returncode == 1
    assert "committed big.py" in result.stderr
    assert "staged_big.py" not in result.stderr


def test_nothing_staged_passes(repo: Repo) -> None:
    result = repo.check()

    assert result.returncode == 0
    assert result.stderr == ""


def test_deleted_file_is_ignored(repo: Repo) -> None:
    repo.stage("old_big.py", "x" * 30_000)
    repo.commit()
    repo.git("rm", "-q", "old_big.py")

    assert repo.check().returncode == 0


def test_generated_file_passes_at_any_size(repo: Repo) -> None:
    repo.stage(".gitattributes", "uv.lock linguist-generated\ncontract/goldens/*.json linguist-generated=true\n")
    repo.stage("uv.lock", "x" * 150_000)
    repo.stage("contract/goldens/slate.json", "x" * 40_000)

    result = repo.check()

    assert result.returncode == 0, result.stderr


def test_binary_file_passes_at_any_size(repo: Repo) -> None:
    repo.stage("assets/logo.png", b"\x89PNG\x00\x01" * 10_000)

    assert repo.check().returncode == 0


def test_grandfathered_file_passes_at_its_budget(repo: Repo) -> None:
    repo.stage(".gitattributes", "legacy/huge.py token-budget=7500\n")
    repo.stage("legacy/huge.py", "x" * 30_000)

    assert repo.check().returncode == 0


def test_grandfathered_file_fails_once_it_grows_past_its_budget(repo: Repo) -> None:
    repo.stage(".gitattributes", "legacy/huge.py token-budget=7500\n")
    repo.stage("legacy/huge.py", "x" * 30_040)

    result = repo.check()

    assert result.returncode == 1
    assert "legacy/huge.py: 7510 tokens, budget 7500, over by 10" in result.stderr


@pytest.mark.parametrize(
    ("path", "recipe_fact"),
    [
        ("src/pkg/engine.py", "package"),
        ("tests/test_engine.py", "helper module"),
        ("docs/GUIDE.md", "H2"),
        ("src/lib/shifts.ts", "barrel"),
        ("src/components/Rail.tsx", "barrel"),
        ("src/lib/__tests__/shifts.test.ts", "test kit"),
        ("src/test/route.test.tsx", "test kit"),
        ("data/notes.txt", "smaller files"),
    ],
)
def test_failure_explains_how_to_split_that_kind_of_file(repo: Repo, path: str, recipe_fact: str) -> None:
    repo.stage(path, "x" * 30_000)

    result = repo.check()

    assert result.returncode == 1
    assert recipe_fact in result.stderr
    assert "See docs/CONVENTIONS.md#token-budget" in result.stderr


def test_python_module_recipe_is_not_given_for_a_test_file(repo: Repo) -> None:
    repo.stage("tests/test_engine.py", "x" * 30_000)

    assert "package" not in repo.check().stderr
