"""How the VIP-presence verdict gates each CompletionProcessor milestone.

Warning and live need a confirmed VIP (``present`` or ``unknown_capped``);
completed and soft-finish are suppressed only by ``absent``. A suppressed
milestone records nothing, so it is never retried.
"""

import pytest

from dk_results.notifications.vip_presence import VIP_ABSENT, VIP_PRESENT, VIP_UNKNOWN, VIP_UNKNOWN_CAPPED

STRICT = {VIP_PRESENT: True, VIP_UNKNOWN_CAPPED: True, VIP_UNKNOWN: False, VIP_ABSENT: False}
LOOSE = {VIP_PRESENT: True, VIP_UNKNOWN_CAPPED: True, VIP_UNKNOWN: True, VIP_ABSENT: False}

# milestone -> (verdict policy, events recorded when the send is suppressed)
MILESTONES = {
    "warning": (STRICT, []),
    "live": (STRICT, []),
    "completed": (LOOSE, ["live"]),
    "soft-finish": (LOOSE, []),
}
CASES = [
    (name, verdict) for name in MILESTONES for verdict in (VIP_PRESENT, VIP_UNKNOWN_CAPPED, VIP_UNKNOWN, VIP_ABSENT)
]


@pytest.fixture
def run_milestone(run_warning, run_live, run_completed, run_soft_finish):
    """``run_milestone(name, presence=...)``: seed and run one milestone, returning the sender."""
    runners = {
        "warning": run_warning,
        "live": run_live,
        "completed": run_completed,
        "soft-finish": run_soft_finish,
    }
    return lambda name, **kwargs: runners[name](**kwargs)


@pytest.mark.parametrize(("milestone", "verdict"), CASES, ids=[f"{m}-{v}" for m, v in CASES])
def test_milestone_is_sent_or_suppressed_by_its_presence_policy(
    run_milestone, scenario, make_presence, stored_events, milestone, verdict
):
    policy, suppressed_events = MILESTONES[milestone]
    sender = run_milestone(milestone, presence=make_presence(verdict))
    assert (len(sender.messages) == 1) is policy[verdict]
    if not policy[verdict]:
        assert stored_events(scenario.dk_id) == suppressed_events


@pytest.mark.parametrize("milestone", list(MILESTONES))
def test_milestone_is_sent_when_no_presence_oracle_is_wired(run_milestone, milestone):
    assert len(run_milestone(milestone, presence=None).messages) == 1


@pytest.fixture
def live_contest(insert_contest, detail, make_results):
    """An UPCOMING contest that DraftKings reports LIVE, so a live announcement is due."""
    insert_contest(status="UPCOMING")
    return make_results(detail=detail(status="LIVE"))


@pytest.mark.parametrize("verdict", [VIP_ABSENT, VIP_UNKNOWN])
def test_a_verdict_other_than_present_suppresses_the_live_announcement(
    conn, sender, live_contest, make_presence, make_processor, verdict
):
    """Warning/live require a *confirmed* VIP: ``absent`` and plain ``unknown`` suppress."""
    presence = make_presence(verdict)
    make_processor(results=live_contest, sender=sender, presence=presence).run(conn)

    assert sender.messages == []
    assert presence.calls[0] == (1, "2024-01-01 00:00:00", [])  # the policy consulted the oracle


def test_unknown_capped_verdict_allows_live_announcement(
    conn, sender, live_contest, make_presence, make_processor, bare_text
):
    """A page-cap-limited scan is structural, not a resolved verdict: still announce."""
    make_processor(results=live_contest, sender=sender, presence=make_presence(VIP_UNKNOWN_CAPPED)).run(conn)

    assert sender.messages == [bare_text("Contest started")]


def test_unknown_verdict_allows_soft_finish(run_soft_finish, make_presence):
    sender = run_soft_finish(presence=make_presence(VIP_UNKNOWN))

    assert [m.splitlines()[0] for m in sender.messages] == ["Contest soft-finished: 🏀 NBA — Main Slate"]


def test_present_verdict_allows_live_announcement(conn, sender, live_contest, make_presence, make_processor, bare_text):
    make_processor(results=live_contest, sender=sender, presence=make_presence(VIP_PRESENT)).run(conn)

    assert sender.messages == [bare_text("Contest started")]


def test_no_presence_oracle_behaves_like_unknown_and_allows_live_announcement(
    conn, sender, live_contest, make_processor, bare_text
):
    make_processor(results=live_contest, sender=sender, presence=None).run(conn)

    assert sender.messages == [bare_text("Contest started")]
