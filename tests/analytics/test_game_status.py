import pytest

from dk_results.analytics.game_status import classify_game_status, sport_has_game_status


@pytest.mark.parametrize(
    ("text", "remaining", "in_play"),
    [
        ("In Progress", True, True),
        ("In-Progress", True, True),
        ("  in-progress ", True, True),
        ("IN  PROGRESS", True, True),
        ("Delayed", True, True),
        ("Suspended", True, True),
        ("LAL@BOS 07:30PM ET", True, False),
        ("BOS@LAL 10:00PM ET", True, False),
        ("Final", False, False),
        ("final", False, False),
        ("Postponed", False, False),
        ("Cancelled", False, False),
        ("Canceled", False, False),
        ("Masters Tournament", None, None),
        ("", None, None),
        (None, None, None),
    ],
)
def test_classify_game_status_table(text, remaining, in_play) -> None:
    status = classify_game_status(text)

    assert status.remaining is remaining
    assert status.in_play is in_play


def test_sport_has_game_status_is_false_when_every_status_is_unknown() -> None:
    assert sport_has_game_status(["Masters Tournament", "Masters Tournament", "", None]) is False


def test_sport_has_game_status_is_false_for_empty_pool() -> None:
    assert sport_has_game_status([]) is False


@pytest.mark.parametrize("known", ["Final", "In Progress", "LAL@BOS 07:30PM ET", "Postponed"])
def test_sport_has_game_status_is_true_when_any_status_classifies(known) -> None:
    assert sport_has_game_status(["Masters Tournament", known]) is True
