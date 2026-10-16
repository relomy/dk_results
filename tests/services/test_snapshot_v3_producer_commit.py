from __future__ import annotations

from dk_results.services.snapshot_v3.producer_commit import resolve_producer_commit

HEAD_SHA = "0123456789abcdef0123456789abcdef01234567"
OTHER_SHA = "fedcba9876543210fedcba9876543210fedcba98"


class FakeGit:
    """Fake git runner: maps an argument list to its stdout, or raises."""

    def __init__(self, outputs: dict[tuple[str, ...], str] | None = None, error: Exception | None = None) -> None:
        self.outputs = outputs or {}
        self.error = error
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, args: list[str]) -> str:
        self.calls.append(tuple(args))
        if self.error is not None:
            raise self.error
        return self.outputs[tuple(args)]


def clean_git(sha: str = HEAD_SHA) -> FakeGit:
    return FakeGit(
        {
            ("rev-parse", "HEAD"): f"{sha}\n",
            ("status", "--porcelain", "--untracked-files=no"): "",
        }
    )


def test_valid_environment_override_wins_without_running_git() -> None:
    git = FakeGit(error=AssertionError("git must not run"))

    assert resolve_producer_commit({"DK_RESULTS_COMMIT": OTHER_SHA}, git) == OTHER_SHA
    assert git.calls == []


def test_invalid_environment_override_is_ignored() -> None:
    for bad in ("", "abc123", OTHER_SHA.upper(), OTHER_SHA + "0", "g" * 40):
        assert resolve_producer_commit({"DK_RESULTS_COMMIT": bad}, clean_git()) == HEAD_SHA


def test_clean_checkout_returns_head() -> None:
    assert resolve_producer_commit({}, clean_git()) == HEAD_SHA


def test_uncommitted_tracked_changes_give_none() -> None:
    git = FakeGit(
        {
            ("rev-parse", "HEAD"): f"{HEAD_SHA}\n",
            ("status", "--porcelain", "--untracked-files=no"): " M src/dk_results/cli/snapshot_feed.py\n",
        }
    )

    assert resolve_producer_commit({}, git) is None


def test_git_failure_gives_none() -> None:
    assert resolve_producer_commit({}, FakeGit(error=OSError("git not installed"))) is None


def test_malformed_head_output_gives_none() -> None:
    git = FakeGit(
        {
            ("rev-parse", "HEAD"): "HEAD\n",
            ("status", "--porcelain", "--untracked-files=no"): "",
        }
    )

    assert resolve_producer_commit({}, git) is None
