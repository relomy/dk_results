"""Trimmed copies of real DraftKings draftables payloads, fetched 2026-10-03.

CFB draft group 154161 keeps one Live Competition (UF @ MIZZ) and one
ScoresOfficial Competition (BAMA @ MSST), each with a home and an away player.
GOLF draft group 154289 keeps its only Competition, the tournament, whose home
and away teams are both ``Golf``. A few fields the adapter ignores are kept to
exercise ``extra="ignore"``. The accessors return fresh copies so tests can
mutate them.
"""

import copy
from typing import Any

_CFB: dict[str, Any] = {
    "draftables": [
        {
            "draftableId": 44324599,
            "displayName": "Jamal Roberts",
            "position": "RB",
            "salary": 7300,
            "teamAbbreviation": "MIZZ",
            "competition": {"competitionId": 6182214, "name": "UF @ MIZZ", "startTime": "2026-10-03T19:30:00.0000000Z"},
        },
        {
            "draftableId": 44324584,
            "displayName": "Jadan Baugh",
            "position": "RB",
            "salary": 9800,
            "teamAbbreviation": "UF",
            "competition": {"competitionId": 6182214, "name": "UF @ MIZZ", "startTime": "2026-10-03T19:30:00.0000000Z"},
        },
        {
            "draftableId": 44324334,
            "displayName": "Kamario Taylor",
            "position": "QB",
            "salary": 8100,
            "teamAbbreviation": "MSST",
            "competition": {
                "competitionId": 6182213,
                "name": "BAMA @ MSST",
                "startTime": "2026-10-03T16:00:00.0000000Z",
            },
        },
        {
            "draftableId": 44324318,
            "displayName": "Keelon Russell",
            "position": "QB",
            "salary": 8800,
            "teamAbbreviation": "BAMA",
            "competition": {
                "competitionId": 6182213,
                "name": "BAMA @ MSST",
                "startTime": "2026-10-03T16:00:00.0000000Z",
            },
        },
    ],
    "competitions": [
        {
            "competitionId": 6182214,
            "homeTeam": {"abbreviation": "MIZZ", "city": "Missouri"},
            "awayTeam": {"abbreviation": "UF", "city": "Florida"},
            "competitionState": "Live",
            "name": "UF @ MIZZ",
            "startTime": "2026-10-03T19:30:00.0000000Z",
        },
        {
            "competitionId": 6182213,
            "homeTeam": {"abbreviation": "MSST", "city": "Mississippi State"},
            "awayTeam": {"abbreviation": "BAMA", "city": "Alabama"},
            "competitionState": "ScoresOfficial",
            "name": "BAMA @ MSST",
            "startTime": "2026-10-03T16:00:00.0000000Z",
        },
    ],
}

_GOLF: dict[str, Any] = {
    "draftables": [
        {
            "draftableId": 44384982,
            "displayName": "Benjamin James",
            "position": "G",
            "salary": 11000,
            "teamAbbreviation": "Golf",
            "competition": {
                "competitionId": 6161422,
                "name": "Bank of Utah Championship",
                "startTime": "2026-10-04T10:00:00.0000000Z",
            },
        },
        {
            "draftableId": 44384983,
            "displayName": "Jackson Koivun",
            "position": "G",
            "salary": 10800,
            "teamAbbreviation": "Golf",
            "competition": {
                "competitionId": 6161422,
                "name": "Bank of Utah Championship",
                "startTime": "2026-10-04T10:00:00.0000000Z",
            },
        },
    ],
    "competitions": [
        {
            "competitionId": 6161422,
            "homeTeam": {"abbreviation": "Golf", "city": ""},
            "awayTeam": {"abbreviation": "Golf", "city": ""},
            "competitionState": "Upcoming",
            "name": "Bank of Utah Championship",
            "startTime": "2026-10-04T10:00:00.0000000Z",
        }
    ],
}


def cfb_payload() -> dict[str, Any]:
    return copy.deepcopy(_CFB)


def golf_payload() -> dict[str, Any]:
    return copy.deepcopy(_GOLF)
