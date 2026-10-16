"""Resolve the producer commit that stamps a snapshot envelope."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping

COMMIT_ENV_VAR = "DK_RESULTS_COMMIT"

_SHA_PATTERN = re.compile(r"[0-9a-f]{40}")

GitRunner = Callable[[list[str]], str]


def _valid_sha(value: str | None) -> str | None:
    candidate = (value or "").strip()
    return candidate if _SHA_PATTERN.fullmatch(candidate) else None


def resolve_producer_commit(env: Mapping[str, str], run_git: GitRunner) -> str | None:
    """Return the producer's 40-character commit SHA, or ``None`` when it cannot be told.

    ``DK_RESULTS_COMMIT`` wins when it holds a valid SHA. Otherwise the checkout's
    ``HEAD`` is used, unless tracked files have uncommitted changes. Never raises.
    """
    override = _valid_sha(env.get(COMMIT_ENV_VAR))
    if override is not None:
        return override
    try:
        head = _valid_sha(run_git(["rev-parse", "HEAD"]))
        if head is None or run_git(["status", "--porcelain", "--untracked-files=no"]).strip():
            return None
        return head
    except Exception:
        return None
