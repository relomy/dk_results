"""Path helpers for robust repo-root-relative file resolution."""

from __future__ import annotations

from pathlib import Path


def find_repo_root(start: Path | None = None) -> Path:
    current = (start or Path(__file__).resolve()).resolve()
    if current.is_file():
        current = current.parent

    for candidate in [current, *current.parents]:
        if (candidate / "pyproject.toml").is_file():
            return candidate
        if (candidate / ".git").exists():
            return candidate
    raise RuntimeError("Unable to determine repository root from current path")


def repo_root() -> Path:
    return find_repo_root(Path(__file__).resolve())


def repo_file(*parts: str) -> Path:
    return repo_root().joinpath(*parts)
