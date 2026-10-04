"""Golden envelopes: complete snapshots built by the real pipeline from fixed scenario bundles.

Each scenario in ``snapshot_scenarios.SCENARIOS`` is rebuilt (injected collector, real derive,
builder and validators, fixed ``generated_at``) and compared byte for byte with the file committed
at ``contract/goldens/<scenario>.json``. An intentional shape change is reviewed as a diff of
those files; rewrite them all in one step with the command in ``REGENERATE_COMMAND``.
"""

from __future__ import annotations

import json
import os
from operator import attrgetter
from typing import Any

import pytest

from dk_results.paths import repo_file
from dk_results.services.json_stable import to_stable_json
from tests.services.snapshot_scenarios import SCENARIOS, Scenario, build_envelope

REGENERATE_ENV = "UPDATE_GOLDENS"
REGENERATE_COMMAND = f"{REGENERATE_ENV}=1 uv run pytest tests/services/test_snapshot_v3_goldens.py"
GOLDENS_DIR = repo_file("contract", "goldens")


def _golden_path(name: str):
    return GOLDENS_DIR / f"{name}.json"


def _committed_contest(name: str) -> dict[str, Any]:
    """The scenario's single contest, read from the committed file the way a consumer reads it."""
    envelope = json.loads(_golden_path(name).read_text())
    (payload,) = envelope["sports"].values()
    (contest,) = payload["contests"]
    return contest


@pytest.mark.parametrize("scenario", SCENARIOS, ids=attrgetter("name"))
def test_rebuilt_envelope_matches_the_committed_golden(scenario: Scenario) -> None:
    rebuilt = to_stable_json(build_envelope(scenario))
    path = _golden_path(scenario.name)
    if os.environ.get(REGENERATE_ENV) == "1":
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rebuilt, encoding="utf-8")

    committed = path.read_text() if path.is_file() else ""

    assert committed == rebuilt, (
        f"{path.relative_to(repo_file())} no longer matches the envelope the pipeline builds for "
        f"scenario {scenario.name!r}. If the change is intentional, regenerate every golden with "
        f"`{REGENERATE_COMMAND}` and review the diff; otherwise fix the regression."
    )


def test_every_committed_golden_belongs_to_a_scenario() -> None:
    committed = {path.stem for path in GOLDENS_DIR.glob("*.json")}

    assert committed == {scenario.name for scenario in SCENARIOS}, (
        f"contract/goldens/ and the scenario registry disagree; regenerate with `{REGENERATE_COMMAND}` "
        "and delete goldens of removed scenarios."
    )


def test_golf_golden_has_no_game_status_and_omits_every_remaining_figure() -> None:
    envelope = json.loads(_golden_path("golf").read_text())
    (payload,) = envelope["sports"].values()
    contest = _committed_contest("golf")

    assert {player["game_status"] for player in payload["players"]} == {"Masters Tournament"}
    assert "ownership_watchlist" not in contest
    assert all("ownership_remaining_total_pct" not in row for row in contest["standings"])
    assert set(contest["live_metrics"]) == {"cash_line", "updated_at"}
    assert "threat" not in contest["metrics"]
    assert "top_remaining_players" not in contest["metrics"]["non_cashing"]
    assert all("ownership_in_play_pct" not in row for row in contest["metrics"]["ownership_summary"]["per_vip"])
