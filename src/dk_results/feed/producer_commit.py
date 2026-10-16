"""Resolve the producer commit that stamps a snapshot envelope."""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Mapping

from dk_results.services.snapshot_v3.constants import PRODUCER_COMMIT_PATTERN

logger = logging.getLogger(__name__)

COMMIT_ENV_VAR = "DK_RESULTS_COMMIT"

_SHA = re.compile(PRODUCER_COMMIT_PATTERN)

GitRunner = Callable[[list[str]], str]


def _from_checkout(run_git: GitRunner) -> str | None:
    head = run_git(["rev-parse", "HEAD"]).strip()
    if not _SHA.fullmatch(head):
        logger.debug("producer commit unknown: git HEAD is not a full SHA")
        return None
    if run_git(["status", "--porcelain", "--untracked-files=no"]).strip():
        logger.debug("producer commit unknown: checkout has uncommitted changes to tracked files")
        return None
    return head


def resolve_producer_commit(env: Mapping[str, str], run_git: GitRunner) -> str | None:
    """Return the producer's 40-character commit SHA, or ``None`` when it cannot be told.

    ``DK_RESULTS_COMMIT`` wins when it is exactly a valid SHA. Otherwise the checkout's
    ``HEAD`` is used, unless tracked files have uncommitted changes. Never raises.
    """
    try:
        override = env.get(COMMIT_ENV_VAR)
        if override is not None and _SHA.fullmatch(override):
            return override
        return _from_checkout(run_git)
    except Exception:
        logger.debug("producer commit unknown: could not read it from the checkout", exc_info=True)
        return None
