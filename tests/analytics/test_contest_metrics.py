from types import SimpleNamespace

import pytest

from dk_results.analytics.contest_metrics import average_remaining_salary, remaining_ownership


def test_remaining_ownership_ignores_final_slots() -> None:
    assert (
        remaining_ownership([{"game_info": "Final", "ownership": 0.8}, {"game_info": "Live", "ownership": 0.25}])
        == 25.0
    )


def test_remaining_salary_and_average_are_pure() -> None:
    users = [
        SimpleNamespace(lineupobj=SimpleNamespace(lineup=[SimpleNamespace(salary=10000, game_info="Live")])),
        SimpleNamespace(lineupobj=SimpleNamespace(lineup=[SimpleNamespace(salary=5000, game_info="Live")])),
    ]
    assert average_remaining_salary(users) == 7500.0


FINISHED = ["Final", "Postponed", "Cancelled", "Canceled"]
STILL_TO_SCORE = ["In Progress", "In-Progress", "Delayed", "Suspended", "LAL@BOS 07:30PM ET"]


@pytest.mark.parametrize("status", FINISHED)
def test_remaining_ownership_excludes_finished_statuses(status) -> None:
    slots = [{"game_info": status, "ownership": 0.8}, {"game_info": "In Progress", "ownership": 0.25}]

    assert remaining_ownership(slots) == 25.0


@pytest.mark.parametrize("status", STILL_TO_SCORE)
def test_remaining_ownership_includes_unfinished_statuses(status) -> None:
    assert remaining_ownership([{"game_info": status, "ownership": 0.5}]) == 50.0


def test_remaining_ownership_counts_unknown_status_as_not_finished() -> None:
    assert remaining_ownership([{"game_info": "Masters Tournament", "ownership": 0.5}]) == 50.0


def _user(*statuses_and_salaries):
    lineup = [SimpleNamespace(salary=salary, game_info=status) for status, salary in statuses_and_salaries]
    return SimpleNamespace(lineupobj=SimpleNamespace(lineup=lineup))


@pytest.mark.parametrize("status", FINISHED)
def test_average_remaining_salary_excludes_finished_statuses(status) -> None:
    users = [_user((status, 9000), ("In Progress", 5000))]

    assert average_remaining_salary(users) == 5000.0


@pytest.mark.parametrize("status", STILL_TO_SCORE)
def test_average_remaining_salary_includes_unfinished_statuses(status) -> None:
    users = [_user((status, 6000), ("Final", 9000))]

    assert average_remaining_salary(users) == 6000.0


def test_average_remaining_salary_is_slot_weighted_across_entries() -> None:
    users = [_user(("In Progress", 10000), ("Delayed", 8000)), _user(("LAL@BOS 07:30PM ET", 6000), ("Final", 1))]

    assert average_remaining_salary(users) == 8000.0


def test_average_remaining_salary_is_none_when_every_slot_is_finished() -> None:
    assert average_remaining_salary([_user(("Final", 5000), ("Postponed", 4000))]) is None
