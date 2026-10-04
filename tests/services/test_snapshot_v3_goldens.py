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
from dk_results.services.snapshot_v3.models.envelope import contract_violations
from dk_results.services.snapshot_v3.validate import validate_v3_envelope
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


def test_zero_vip_golden_carries_field_metrics_and_no_vip_metrics() -> None:
    contest = _committed_contest("zero_vip")

    assert contest["vip_lineups"] == []
    assert not any(row["is_vip"] for row in contest["standings"])
    assert contest["live_metrics"]["avg_salary_per_player_remaining"] > 0
    assert {"non_cashing", "threat"} <= set(contest["metrics"])
    assert contest["metrics"]["threat"]["field_remaining_pct"] > 0
    assert not {"distance_to_cash", "ownership_summary"} & set(contest["metrics"])
    assert "vip_vs_field_leverage" not in contest["metrics"]["threat"]


def test_mlb_golden_has_no_non_cashing_tally_and_no_swing_players() -> None:
    contest = _committed_contest("mlb")

    assert contest["metrics"]["non_cashing"]["users_not_cashing"] > 0
    assert "top_remaining_players" not in contest["metrics"]["non_cashing"]
    assert "top_swing_players" not in contest["metrics"]["threat"]
    assert contest["metrics"]["threat"]["vip_vs_field_leverage"]
    assert contest["vip_lineups"]


# NFL mid-slate: 20 entries, 10 paid positions. Rows rank 1, 2, 2, 4, 5, 5, 5, 8, 9, 10, 10, 12, 13, 14, 14,
# 16..20, so 11 rows cash (ties inside the line and at it) and 9 do not. Standings keep the first 6 rows,
# none of them a VIP.
NFL_ENTRIES, NFL_POSITIONS_PAID = 20, 10
NFL_CASHING_ROWS = 11
NFL_NON_CASHING_PMRS = (540.0, 540.0, 570.0, 570.0, 570.0, 600.0, 600.0, 600.0, 600.0)


def test_nfl_mid_slate_golden_passes_model_and_semantic_validation() -> None:
    envelope = json.loads(_golden_path("nfl_mid_slate").read_text())

    assert contract_violations(envelope) == []
    assert validate_v3_envelope(envelope) == []


def test_nfl_mid_slate_golden_standings_stop_before_the_vips() -> None:
    contest = _committed_contest("nfl_mid_slate")

    assert [row["rank"] for row in contest["standings"]] == [1, 2, 2, 4, 5, 5]
    assert not any(row["is_vip"] for row in contest["standings"])


def test_nfl_mid_slate_golden_keeps_vips_ranked_beyond_the_standings_cut_in_every_vip_section() -> None:
    contest = _committed_contest("nfl_mid_slate")
    vips = {row["display_name"]: row["rank"] for row in contest["vip_lineups"]}

    assert vips == {"EmpireMaker2": 8, "vip_at_line": 10, "vip_below_a": 13, "vip_below_b": 17}
    assert {row["display_name"] for row in contest["metrics"]["distance_to_cash"]["per_vip"]} == set(vips)
    assert {row["display_name"] for row in contest["metrics"]["ownership_summary"]["per_vip"]} == set(vips)


def test_nfl_mid_slate_golden_emits_vip_rank_points_and_pmr_as_numbers() -> None:
    contest = _committed_contest("nfl_mid_slate")

    for vip in contest["vip_lineups"]:
        assert type(vip["rank"]) is int and type(vip["points"]) is float and type(vip["pmr"]) is float
        assert "pts" not in vip
    below_a = next(vip for vip in contest["vip_lineups"] if vip["display_name"] == "vip_below_a")
    assert (below_a["rank"], below_a["points"], below_a["pmr"]) == (13, 116.0, 540.0)


def test_nfl_mid_slate_golden_trims_the_padded_dst_name_in_vip_lineups() -> None:
    contest = _committed_contest("nfl_mid_slate")

    revealed = [slot for vip in contest["vip_lineups"] for slot in vip["players_live"] if not slot.get("is_locked")]
    assert {slot["player_name"] for slot in revealed if slot["slot"] == "DST"} == {"Rams", "Jets"}
    assert all(slot["player_name"] == slot["player_name"].strip() for slot in revealed)


def test_nfl_mid_slate_golden_trims_names_in_every_other_section_and_matches_the_vip_defense() -> None:
    envelope = json.loads(_golden_path("nfl_mid_slate").read_text())
    contest = _committed_contest("nfl_mid_slate")

    swing = [row["player_name"] for row in contest["metrics"]["threat"]["top_swing_players"]]
    non_cashing = [row["player_name"] for row in contest["metrics"]["non_cashing"]["top_remaining_players"]]
    players = [player["name"] for player in next(iter(envelope["sports"].values()))["players"]]
    assert all(name == name.strip() for name in swing + non_cashing + players)
    assert "Rams" in swing and "Rams" in players


def test_nfl_mid_slate_golden_carries_locked_slots_next_to_revealed_ones() -> None:
    contest = _committed_contest("nfl_mid_slate")

    for vip in contest["vip_lineups"]:
        locked = [slot for slot in vip["players_live"] if slot.get("is_locked")]
        revealed = [slot for slot in vip["players_live"] if not slot.get("is_locked")]
        assert locked and revealed
        assert all(slot["player_name"] == "LOCKED \N{LOCK}" for slot in locked)
        assert all({"player_key", "salary"} & slot.keys() == set() for slot in locked)
        assert all(slot["is_live"] in (True, False) and slot["salary"] > 0 for slot in revealed)


def test_nfl_mid_slate_golden_non_cashing_stays_within_entries_minus_positions_paid() -> None:
    contest = _committed_contest("nfl_mid_slate")
    cash_line = contest["live_metrics"]["cash_line"]

    assert contest["max_entries"] == NFL_ENTRIES
    assert cash_line["rank_cutoff"] == NFL_POSITIONS_PAID
    assert contest["metrics"]["non_cashing"]["users_not_cashing"] <= NFL_ENTRIES - cash_line["rank_cutoff"]


def test_nfl_mid_slate_golden_does_not_count_ties_at_or_inside_the_cash_line_as_non_cashing() -> None:
    contest = _committed_contest("nfl_mid_slate")
    non_cashing = contest["metrics"]["non_cashing"]

    # 20 entries minus the 11 rows at or inside rank 10 (ties inside the line, two tied at it).
    assert non_cashing["users_not_cashing"] == NFL_ENTRIES - NFL_CASHING_ROWS
    assert non_cashing["avg_pmr_remaining"] == round(sum(NFL_NON_CASHING_PMRS) / len(NFL_NON_CASHING_PMRS), 2)
    tied_inside = [row for row in contest["standings"] if row["rank"] in (2, 5)]
    assert len(tied_inside) == 4 and all(row["is_cashing"] for row in tied_inside)
    assert contest["live_metrics"]["cash_line"]["points_cutoff"] == 128.02
    assert {row["display_name"]: row["rank_delta"] for row in contest["metrics"]["distance_to_cash"]["per_vip"]} == {
        "EmpireMaker2": 2,
        "vip_at_line": 0,
        "vip_below_a": -3,
        "vip_below_b": -7,
    }
    # The tied cashing rows alone roster McConkey (still playing); he must not enter the non-cashing tally.
    assert "Ladd McConkey" not in {row["player_name"] for row in non_cashing["top_remaining_players"]}
