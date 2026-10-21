"""Presence rules: warnings from collect_presence_warnings, never violations."""

import pytest

from dk_results.services.snapshot_v3.validate import collect_presence_warnings, validate_v3_envelope
from tests.services.snapshot_v3_validate_builders import _valid_envelope

# --- presence rules: warnings, never violations ---------------------------------------------------

CONTEST = "sports.nba.contests[0]"


def _presence_envelope(*, standings=None, vip_lineups=None, players=None) -> dict:
    payload = _valid_envelope()
    sport = payload["sports"]["nba"]
    sport["players"] = players if players is not None else []
    sport["contests"][0]["standings"] = standings if standings is not None else []
    sport["contests"][0]["vip_lineups"] = vip_lineups if vip_lineups is not None else []
    return payload


def _warning(path: str, rule: str) -> dict:
    return {"path": path, "rule": rule}


def test_presence_warnings_are_empty_for_an_envelope_with_nothing_to_check() -> None:
    assert collect_presence_warnings(_valid_envelope()) == []


def test_cashing_row_with_a_payout_meets_the_payout_rule() -> None:
    payload = _presence_envelope(standings=[{"is_cashing": True, "payout_cents": 1800}])
    assert collect_presence_warnings(payload) == []


def test_cashing_row_without_a_payout_is_warned_once_with_path_and_rule() -> None:
    payload = _presence_envelope(standings=[{"is_cashing": False}, {"is_cashing": True, "payout_cents": None}])
    assert collect_presence_warnings(payload) == [
        _warning(f"{CONTEST}.standings[1].payout_cents", "cashing_row_has_payout")
    ]


def test_non_cashing_row_without_a_payout_is_not_warned() -> None:
    payload = _presence_envelope(standings=[{"is_cashing": False, "payout_cents": None}, {"payout_cents": None}])
    assert collect_presence_warnings(payload) == []


def _vip(*slots: dict) -> dict:
    return {"display_name": "vip", "players_live": list(slots)}


def test_unlocked_vip_slot_with_a_player_key_meets_the_player_key_rule() -> None:
    payload = _presence_envelope(vip_lineups=[_vip({"slot": "PG", "player_name": "A", "player_key": "nba:a"})])
    assert collect_presence_warnings(payload) == []


def test_unlocked_vip_slot_without_a_player_key_is_warned_once_with_path_and_rule() -> None:
    payload = _presence_envelope(
        vip_lineups=[
            _vip({"slot": "PG", "player_name": "A", "player_key": "nba:a"}, {"slot": "SG", "player_name": "B"})
        ]
    )
    assert collect_presence_warnings(payload) == [
        _warning(f"{CONTEST}.vip_lineups[0].players_live[1].player_key", "unlocked_vip_slot_has_player_key")
    ]


def test_locked_vip_slot_without_a_player_key_is_not_warned() -> None:
    payload = _presence_envelope(vip_lineups=[_vip({"slot": "PG", "player_name": "LOCKED 🔒", "is_locked": True})])
    assert collect_presence_warnings(payload) == []


def test_in_progress_player_with_stats_and_projection_meets_the_stats_rule() -> None:
    player = {"name": "A", "game_status": "In Progress", "stats_text": "1 HR", "rt_projection": 12.5}
    assert collect_presence_warnings(_presence_envelope(players=[player])) == []


def test_in_progress_player_missing_stats_and_projection_gets_one_warning_per_field() -> None:
    payload = _presence_envelope(players=[{"name": "A", "game_status": "In Progress"}])
    assert collect_presence_warnings(payload) == [
        _warning("sports.nba.players[0].stats_text", "in_progress_player_has_stats"),
        _warning("sports.nba.players[0].rt_projection", "in_progress_player_has_stats"),
    ]


def test_in_progress_player_missing_only_the_projection_is_warned_for_the_projection() -> None:
    player = {"name": "A", "game_status": "In Progress", "stats_text": "1 HR"}
    assert collect_presence_warnings(_presence_envelope(players=[player])) == [
        _warning("sports.nba.players[0].rt_projection", "in_progress_player_has_stats")
    ]


@pytest.mark.parametrize("status", ["Final", "NYY@BOS 07:10PM ET", "Masters Tournament", None])
def test_player_whose_game_is_not_in_progress_is_not_warned(status) -> None:
    assert collect_presence_warnings(_presence_envelope(players=[{"name": "A", "game_status": status}])) == []


def test_presence_rules_do_not_make_the_hand_written_validator_fail() -> None:
    payload = _presence_envelope(standings=[{"is_cashing": True, "payout_cents": None}])
    assert validate_v3_envelope(payload) == []


def test_presence_warnings_tolerate_malformed_sections() -> None:
    payload = _valid_envelope()
    payload["sports"] = {
        "nba": "x",
        "mlb": {"players": "x", "contests": ["x", {"standings": "x", "vip_lineups": ["x"]}]},
    }
    assert collect_presence_warnings(payload) == []
