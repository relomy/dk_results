"""CompletionProcessor soft-finish: what counts as an effectively final leaderboard.

Every part of the payload must be well formed and show zero time remaining; anything
else stays silent. The same shape, all clean, is the control.
"""

import pytest

# Each case is the keyword overrides of the ``leaderboard`` fixture that spoil the clean payload.
SPOILED = {
    "leader-not-object": {"leader": "x"},
    "last-winning-not-object": {"last_winning": "x"},
    "no-rows": {"rows": []},
    "rows-not-a-list": {"rows": "x"},
    "row-not-object": {"rows": ["x"]},
    "leader-still-playing": {"leader": {"timeRemaining": 5, "fantasyPoints": 229}},
    "last-winning-still-playing": {"last_winning": {"timeRemaining": 5, "fantasyPoints": 185.5}},
    "row-still-playing": {
        "rows": [{"userName": "FooBar", "timeRemaining": 5, "fantasyPoints": 229, "winningValue": 100.0}]
    },
    # Time remaining that is not a number never counts as finished.
    "time-remaining-missing": {"leader": {"timeRemaining": None, "fantasyPoints": 229}},
    "time-remaining-bool": {"leader": {"timeRemaining": True, "fantasyPoints": 229}},
    "time-remaining-blank": {"leader": {"timeRemaining": "  ", "fantasyPoints": 229}},
    "time-remaining-not-a-number": {"leader": {"timeRemaining": "soon", "fantasyPoints": 229}},
}


def test_soft_finish_announces_a_well_formed_final_leaderboard(run_soft_finish, leaderboard):
    messages = run_soft_finish(payload=leaderboard()).messages
    assert [m.splitlines()[0] for m in messages] == ["Contest soft-finished: 🏀 NBA — Main Slate"]


@pytest.mark.parametrize("spoiled", SPOILED.values(), ids=SPOILED.keys())
def test_soft_finish_stays_silent_unless_every_part_is_finished(run_soft_finish, leaderboard, spoiled):
    assert run_soft_finish(payload=leaderboard(**spoiled)).messages == []


def test_soft_finish_stays_silent_for_an_empty_payload(run_soft_finish):
    assert run_soft_finish(payload={}).messages == []


@pytest.mark.parametrize("missing", ["leader", "last_winning"])
def test_soft_finish_stays_silent_without_a_score_to_report(run_soft_finish, leaderboard, missing):
    no_score = {"timeRemaining": 0, "fantasyPoints": "n/a"}
    assert run_soft_finish(payload=leaderboard(**{missing: no_score})).messages == []


def test_soft_finish_is_skipped_when_the_live_contest_completes_mid_run(
    conn, sender, insert_contest, detail, leaderboard, make_results, make_processor
):
    insert_contest(status="LIVE")
    # The sync pass sees LIVE (unchanged); by the soft-finish pass it has completed.
    results = make_results(detail=[detail(status="LIVE"), detail(status="COMPLETED")], leaderboard=leaderboard())
    make_processor(results=results, sender=sender, presence=None).run(conn)
    assert sender.messages == []
