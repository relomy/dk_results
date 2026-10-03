"""Boundary-adapter tests for the DraftKings draftables payload (ADR-0003).

The fixtures are trimmed copies of real payloads fetched 2026-10-03:
CFB draft group 154161 (one Live and one ScoresOfficial Competition) and
GOLF draft group 154289 (the tournament as its only Competition).
"""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from dk_results.domain.draftables import Draftables

FIXTURES = Path(__file__).parent / "fixtures"


def _payload(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_live_competition_gives_home_player_vs_away_and_away_player_at_home() -> None:
    matchups = Draftables.from_payload(_payload("draftables_cfb.json")).matchups_by_draftable_id()

    # UF @ MIZZ, Live: MIZZ is home, UF is away.
    assert matchups["44324599"] == "vs. UF"
    assert matchups["44324584"] == "at MIZZ"


def test_final_competition_still_gives_the_opponent() -> None:
    matchups = Draftables.from_payload(_payload("draftables_cfb.json")).matchups_by_draftable_id()

    # BAMA @ MSST, ScoresOfficial: MSST is home, BAMA is away.
    assert matchups["44324334"] == "vs. BAMA"
    assert matchups["44324318"] == "at MSST"


def test_golf_tournament_has_no_matchup() -> None:
    matchups = Draftables.from_payload(_payload("draftables_golf.json")).matchups_by_draftable_id()

    assert matchups == {"44384982": None, "44384983": None}


def test_player_on_neither_team_has_no_matchup() -> None:
    payload = _payload("draftables_cfb.json")
    payload["draftables"][0]["teamAbbreviation"] = "UGA"

    matchups = Draftables.from_payload(payload).matchups_by_draftable_id()

    assert matchups["44324599"] is None


def test_draftable_whose_competition_is_not_listed_has_no_matchup() -> None:
    payload = _payload("draftables_cfb.json")
    payload["draftables"][0]["competition"]["competitionId"] = 1

    matchups = Draftables.from_payload(payload).matchups_by_draftable_id()

    assert matchups["44324599"] is None


@pytest.mark.parametrize(
    ("path", "field"),
    [
        (("draftables", 0, "draftableId"), "draftableId"),
        (("draftables", 0, "teamAbbreviation"), "teamAbbreviation"),
        (("draftables", 0, "competition", "competitionId"), "competitionId"),
        (("competitions", 0, "homeTeam", "abbreviation"), "homeTeam.abbreviation"),
        (("competitions", 0, "awayTeam"), "awayTeam"),
        (("competitions", 0, "competitionState"), "competitionState"),
        (("competitions",), "competitions"),
    ],
)
def test_missing_required_field_raises_naming_field(path, field) -> None:
    payload = _payload("draftables_cfb.json")
    parent = payload
    for key in path[:-1]:
        parent = parent[key]
    del parent[path[-1]]

    with pytest.raises(ValidationError) as excinfo:
        Draftables.from_payload(payload)

    message = str(excinfo.value)
    assert field in message
    assert "Field required" in message


def test_draftables_is_frozen() -> None:
    draftables = Draftables.from_payload(_payload("draftables_golf.json"))

    with pytest.raises(ValidationError):
        draftables.draftables = []
