from types import SimpleNamespace

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
