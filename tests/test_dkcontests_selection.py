"""dkcontests contest selection: largest double-up, fee tiers and fallback."""

import datetime

import dk_results.cli.dkcontests as dkcontests
from dk_results.domain.contest import Contest
from tests.dkcontests_payloads import _contest_payload


def test_get_largest_contest_applies_query_and_exclude():
    contests = [
        Contest.from_lobby(_contest_payload(1, entries=150, fee=25), "NFL"),
        Contest.from_lobby({**_contest_payload(2, entries=260, fee=25), "n": "Main Slate"}, "NFL"),
        Contest.from_lobby({**_contest_payload(3, entries=280, fee=25), "n": "Main Excluded"}, "NFL"),
    ]

    largest = dkcontests.get_largest_contest(
        contests,
        datetime.datetime(2023, 11, 14),
        entry_fee=25,
        query="Main",
        exclude="Excluded",
    )

    assert largest is not None
    assert largest.id == 2


def test_get_largest_contest_applies_game_type_id():
    contests = [
        Contest.from_lobby({**_contest_payload(11, entries=200), "gameTypeId": 6}, "GOLF"),
        Contest.from_lobby({**_contest_payload(12, entries=300), "gameTypeId": 87}, "GOLF"),
    ]

    largest = dkcontests.get_largest_contest(
        contests,
        datetime.datetime(2023, 11, 14),
        entry_fee=25,
        game_type_id=87,
    )

    assert largest is not None
    assert largest.id == 12


def test_get_largest_contest_reports_candidates_eliminated_by_query(capsys):
    contests = [
        Contest.from_lobby({**_contest_payload(1, entries=150, fee=25), "n": "Afternoon Slate"}, "NFL"),
    ]

    largest = dkcontests.get_largest_contest(
        contests,
        datetime.datetime(2023, 11, 14),
        entry_fee=25,
        query="Night",
    )

    assert largest is None
    out = capsys.readouterr().out
    assert "matched none of the $25 double-up(s)" in out
    assert "Afternoon Slate" in out


def test_get_available_dub_fees_returns_descending_distinct_fees():
    date = datetime.datetime(2023, 11, 14)
    timestamp = "1700000000000"
    contests = [
        Contest.from_lobby(_contest_payload(1, fee=25), "NFL"),
        Contest.from_lobby(_contest_payload(2, fee=10), "NFL"),
        Contest.from_lobby(_contest_payload(3, fee=10), "NFL"),
        Contest.from_lobby({**_contest_payload(4, fee=5), "attr": {"IsDoubleUp": False, "IsGuaranteed": True}}, "NFL"),
    ]
    assert all(c.start_dt.date() == date.date() for c in contests), "fixture timestamp drifted"
    del timestamp

    assert dkcontests.get_available_dub_fees(contests, date) == [25, 10]


def test_get_available_dub_fees_restricts_to_game_type_id():
    date = datetime.datetime(2023, 11, 14)
    contests = [
        Contest.from_lobby({**_contest_payload(1, fee=25), "gameTypeId": 87}, "NFL"),
        Contest.from_lobby({**_contest_payload(2, fee=10), "gameTypeId": 6}, "NFL"),
    ]

    assert dkcontests.get_available_dub_fees(contests, date, game_type_id=87) == [25]


def test_get_largest_contest_with_fallback_skips_tiers_outside_game_type_id(capsys):
    contests = [
        Contest.from_lobby({**_contest_payload(1, entries=150, fee=25), "gameTypeId": 87}, "GOLF"),
        Contest.from_lobby({**_contest_payload(2, entries=300, fee=10), "gameTypeId": 6}, "GOLF"),
    ]

    largest = dkcontests.get_largest_contest_with_fallback(
        contests,
        datetime.datetime(2023, 11, 14),
        entry_fee=25,
        query="Night",
        game_type_id=87,
    )

    assert largest is None
    out = capsys.readouterr().out
    assert "[$10]" not in out


def test_get_largest_contest_with_fallback_drops_to_lower_tier(capsys):
    contests = [
        Contest.from_lobby({**_contest_payload(1, entries=150, fee=25), "n": "Afternoon Slate"}, "NFL"),
        Contest.from_lobby({**_contest_payload(2, entries=300, fee=10), "n": "Thursday Night Slate"}, "NFL"),
    ]

    largest = dkcontests.get_largest_contest_with_fallback(
        contests,
        datetime.datetime(2023, 11, 14),
        entry_fee=25,
        query="Night",
    )

    assert largest is not None
    assert largest.id == 2
    assert "falling back to $10" in capsys.readouterr().out


def test_get_largest_contest_with_fallback_labels_each_tiers_diagnostics(capsys):
    contests = [
        Contest.from_lobby({**_contest_payload(1, entries=150, fee=25), "n": "Afternoon Slate"}, "NFL"),
        Contest.from_lobby({**_contest_payload(2, entries=300, fee=10), "n": "Thursday Night Slate"}, "NFL"),
    ]

    dkcontests.get_largest_contest_with_fallback(
        contests,
        datetime.datetime(2023, 11, 14),
        entry_fee=25,
        query="Night",
    )

    out = capsys.readouterr().out
    assert "[$25] contests size:" in out
    assert "[$25] number of contests meeting requirements:" in out
    assert "[$10] contests size:" in out
    assert "[$10] number of contests meeting requirements:" in out


def test_get_largest_contest_with_fallback_no_label_for_single_tier(capsys):
    contests = [
        Contest.from_lobby({**_contest_payload(1, entries=150, fee=25), "n": "Afternoon Slate"}, "NFL"),
    ]

    dkcontests.get_largest_contest_with_fallback(
        contests,
        datetime.datetime(2023, 11, 14),
        entry_fee=25,
    )

    out = capsys.readouterr().out
    assert "contests size: 1" in out
    assert "[$25]" not in out


def test_get_largest_contest_with_fallback_returns_none_when_no_tier_matches():
    contests = [
        Contest.from_lobby({**_contest_payload(1, entries=150, fee=25), "n": "Afternoon Slate"}, "NFL"),
    ]

    largest = dkcontests.get_largest_contest_with_fallback(
        contests,
        datetime.datetime(2023, 11, 14),
        entry_fee=25,
        query="Night",
    )

    assert largest is None
