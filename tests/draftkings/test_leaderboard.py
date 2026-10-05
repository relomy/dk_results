import copy
import json
from pathlib import Path
from typing import Any

from dk_results.draftkings.leaderboard import leaderboard_cash_cents

FIXTURE = Path(__file__).parent / "data" / "leaderboard_194664936.json"


def _fixture_rows() -> list[dict[str, Any]]:
    return json.loads(FIXTURE.read_text())["leaderBoard"]


def test_paid_rows_in_real_leaderboard_decode_to_their_cash_in_cents() -> None:
    paid = [row for row in _fixture_rows() if row.get("winnings")]

    assert [leaderboard_cash_cents(row) for row in paid] == [1000, 1000, 1000]


def test_unpaid_rows_in_real_leaderboard_decode_to_zero_cents() -> None:
    unpaid = [row for row in _fixture_rows() if not row.get("winnings")]

    assert [leaderboard_cash_cents(row) for row in unpaid] == [0, 0]


def test_real_winnings_item_pays_cash_when_the_row_has_no_winning_value() -> None:
    row = copy.deepcopy(next(row for row in _fixture_rows() if row.get("winnings")))
    del row["winningValue"]

    assert leaderboard_cash_cents(row) == 1000


def test_cash_winnings_are_summed_and_non_cash_items_ignored() -> None:
    row = {
        "winnings": [
            {"payoutType": "CASH", "winningValue": "12.34"},
            {"payoutType": "TICKET", "winningValue": "5.00"},
            {"payoutType": "CASH", "winningValue": "0.66"},
        ]
    }

    assert leaderboard_cash_cents(row) == 1300


def test_row_winning_value_wins_over_winnings_items() -> None:
    assert leaderboard_cash_cents({"winningValue": "3.25", "winnings": [{"winningValue": "99.00"}]}) == 325


def test_payout_field_is_the_fallback() -> None:
    assert leaderboard_cash_cents({"payout": "2.50"}) == 250


def test_cash_field_is_the_fallback_after_payout() -> None:
    assert leaderboard_cash_cents({"cash": "1.00"}) == 100


def test_row_with_no_cash_decodes_to_none() -> None:
    assert leaderboard_cash_cents({"winnings": [{"payoutType": "TICKET", "winningValue": "5.00"}]}) is None
    assert leaderboard_cash_cents({}) is None


def test_description_marks_a_winnings_item_as_cash_or_not() -> None:
    assert leaderboard_cash_cents({"winnings": [{"description": "Cash prize", "value": 10}]}) == 1000
    assert leaderboard_cash_cents({"winnings": [{"description": "Ticket", "value": 5}]}) is None


def test_untagged_winnings_item_counts_as_cash() -> None:
    assert leaderboard_cash_cents({"winnings": [{"value": "4.28"}]}) == 428


def test_non_cash_payout_type_wins_over_a_cash_description() -> None:
    row = {"winnings": [{"payoutType": "TICKET", "description": "cash", "value": 5}]}

    assert leaderboard_cash_cents(row) is None


def test_cents_round_half_up() -> None:
    assert leaderboard_cash_cents({"winningValue": "0.005"}) == 1
    assert leaderboard_cash_cents({"winningValue": "0.004"}) == 0
