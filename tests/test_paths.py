from pathlib import Path

from dk_results import paths


def test_repo_root_finds_pyproject_from_nested_start():
    start = Path(__file__).resolve().parent / "classes"
    root = paths.find_repo_root(start)
    assert root == Path(__file__).resolve().parents[1]


def test_repo_file_joins_repo_root():
    resolved = paths.repo_file("config.json")
    assert resolved == Path(__file__).resolve().parents[1] / "config.json"
