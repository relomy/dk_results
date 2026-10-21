"""How the VIP-presence verdict gates each CompletionProcessor milestone.

Warning and live need a confirmed VIP (``present`` or ``unknown_capped``);
completed and soft-finish are suppressed only by ``absent``. A suppressed
milestone records nothing, so it is never retried.
"""

import pytest

from dk_results.notifications.vip_presence import VIP_ABSENT, VIP_PRESENT, VIP_UNKNOWN, VIP_UNKNOWN_CAPPED
from tests.completion_processor_fakes import FixedPresence, make_conn, stored_events
from tests.completion_processor_scenarios import (
    DK_ID,
    run_completed,
    run_live,
    run_soft_finish,
    run_warning,
)

STRICT = {VIP_PRESENT: True, VIP_UNKNOWN_CAPPED: True, VIP_UNKNOWN: False, VIP_ABSENT: False}
LOOSE = {VIP_PRESENT: True, VIP_UNKNOWN_CAPPED: True, VIP_UNKNOWN: True, VIP_ABSENT: False}

# milestone -> (runner, verdict policy, events recorded when the send is suppressed)
MILESTONES = {
    "warning": (lambda conn, mp, **kw: run_warning(conn, mp, **kw), STRICT, []),
    "live": (lambda conn, mp, **kw: run_live(conn, **kw), STRICT, []),
    "completed": (lambda conn, mp, **kw: run_completed(conn, **kw), LOOSE, ["live"]),
    "soft-finish": (lambda conn, mp, **kw: run_soft_finish(conn, **kw), LOOSE, []),
}
CASES = [
    (name, verdict) for name in MILESTONES for verdict in (VIP_PRESENT, VIP_UNKNOWN_CAPPED, VIP_UNKNOWN, VIP_ABSENT)
]


@pytest.fixture
def conn():
    connection = make_conn()
    yield connection
    connection.close()


@pytest.mark.parametrize(("milestone", "verdict"), CASES, ids=[f"{m}-{v}" for m, v in CASES])
def test_milestone_is_sent_or_suppressed_by_its_presence_policy(conn, monkeypatch, milestone, verdict):
    run, policy, suppressed_events = MILESTONES[milestone]
    sender = run(conn, monkeypatch, presence=FixedPresence(verdict))
    assert (len(sender.messages) == 1) is policy[verdict]
    if not policy[verdict]:
        assert stored_events(conn, DK_ID) == suppressed_events


@pytest.mark.parametrize("milestone", list(MILESTONES))
def test_milestone_is_sent_when_no_presence_oracle_is_wired(conn, monkeypatch, milestone):
    run, _policy, _events = MILESTONES[milestone]
    assert len(run(conn, monkeypatch, presence=None).messages) == 1
