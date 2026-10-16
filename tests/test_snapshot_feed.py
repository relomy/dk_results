from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from dk_results.cli import snapshot_feed

ENV_SHA = "fedcba9876543210fedcba9876543210fedcba98"


@pytest.fixture
def feed_calls(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Stub every collaborator of ``main`` and record the keyword arguments of each snapshot build."""
    calls: list[dict[str, Any]] = []

    def _build_live_snapshot(sport_names: list[str], **kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs)
        return {"sports": {}}

    monkeypatch.setattr(snapshot_feed, "load_and_apply_settings", lambda: None)
    monkeypatch.setattr(snapshot_feed, "configure_logging", lambda **_: None)
    monkeypatch.setattr(snapshot_feed, "build_live_snapshot", _build_live_snapshot)
    monkeypatch.setattr(snapshot_feed.R2ObjectStore, "from_env", classmethod(lambda cls: object()))
    monkeypatch.setattr(snapshot_feed, "run_feed", lambda snapshot, store: SimpleNamespace(uploaded_keys=[]))
    return calls


def test_feed_stamps_the_snapshot_with_the_resolved_producer_commit(
    feed_calls: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DK_RESULTS_COMMIT", ENV_SHA)

    assert snapshot_feed.main(["-s", "NBA"]) == 0

    assert [call["producer_commit"] for call in feed_calls] == [ENV_SHA]


def test_feed_resolves_the_producer_commit_from_the_checkout_when_no_override_is_set(
    feed_calls: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("DK_RESULTS_COMMIT", raising=False)

    assert snapshot_feed.main(["-s", "NBA"]) == 0

    (commit,) = (call["producer_commit"] for call in feed_calls)
    assert commit is None or (len(commit) == 40 and commit == commit.lower())
