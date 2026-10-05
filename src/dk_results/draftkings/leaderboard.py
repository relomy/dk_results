"""Decode the cash payout of one DraftKings leaderboard row.

A pure decoder for the ``scores/v1/leaderboards/{contest_id}`` payload: no I/O, no domain types.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any


def leaderboard_cash_cents(row: dict[str, Any]) -> int | None:
    """Return the cash a leaderboard row paid, in integer cents, or ``None`` when it carries none.

    The row's own ``winningValue`` decides first (``0`` for an unpaid entry). Otherwise the cash
    ``winnings[]`` items are summed, then a top-level ``payout`` or ``cash`` is the last fallback.
    """
    winning_value = _dollars_to_cents_half_up(row.get("winningValue"))
    if winning_value is not None:
        return winning_value

    winnings = row.get("winnings")
    if isinstance(winnings, list):
        cash_cents = _sum_cash_winnings(winnings)
        if cash_cents is not None:
            return cash_cents

    for candidate in (row.get("payout"), row.get("cash")):
        cents = _dollars_to_cents_half_up(candidate)
        if cents is not None:
            return cents
    return None


def _sum_cash_winnings(winnings: list[Any]) -> int | None:
    cash_total = 0
    found_cash = False
    for payout in winnings:
        if not isinstance(payout, dict):
            continue
        payout_kind = _first_not_blank(payout.get("payoutType"), payout.get("description"))
        if payout_kind is not None and "cash" not in str(payout_kind).lower():
            continue
        value = _first_not_blank(payout.get("winningValue"), payout.get("value"), payout.get("amount"))
        cents = _dollars_to_cents_half_up(value)
        if cents is not None:
            cash_total += cents
            found_cash = True
    return cash_total if found_cash else None


def _dollars_to_cents_half_up(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    cents = (amount * Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    try:
        return int(cents)
    except (TypeError, ValueError):
        return None


def _first_not_blank(*values: Any) -> Any:
    for value in values:
        if value not in (None, ""):
            return value
    return None
