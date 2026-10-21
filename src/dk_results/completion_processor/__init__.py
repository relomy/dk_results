"""The contest-completion workflow as one deep module.

`CompletionProcessor` advances each tracked contest and announces its
milestones — starting-soon **warning**, **live**, **completed**, and
**soft-finish** — mirroring the `SportProcessor` pattern. Public entry:
``run(conn)``.

Construction-time dependencies are injected; nothing DraftKings-facing is
constructed inline. The work list (incomplete / live / next-upcoming contests)
is read through `ContestDatabase`; the only external DraftKings edge is
`ContestResultsPort` (per ADR 0001, the completion workflow's own DK slice).

The package splits the workflow into collaborators that `CompletionProcessor`
builds from its own dependencies:

- `processor`: `CompletionProcessor`, which runs warnings, the contest-state
  sync loop and soft-finish in order.
- `ports`: `PresenceOracle`, `CompletionProcessorConfig` and the `Now` clock.
- `announcer`: `MilestoneAnnouncer`, the suppression policy plus send + record.
- `messages`: the message text (pure functions).
- `warnings`: `WarningScheduler`, starting-soon warnings.
- `sync`: `ContestSync`, one contest's DraftKings state written back, and its
  live / completed transition.
- `soft_finish`: `SoftFinishAnnouncer` and its summary helpers.

The suppression policy differs by milestone. Warning and live require a
*confirmed* VIP: ``present`` announces, and so does ``unknown_capped`` (the
field is too large to fully scan, a structural fact rather than a resolved
verdict); every other outcome — ``absent`` or a plain ``unknown`` — suppresses
the send, with no retry. Completed and soft-finish keep the original, looser
policy: only ``absent`` suppresses, and any ``unknown`` allows the send.
`VipPresence` stays a pure verdict provider.
"""

from dk_results.completion_processor.messages import _parse_start_date as _parse_start_date
from dk_results.completion_processor.ports import CompletionProcessorConfig as CompletionProcessorConfig
from dk_results.completion_processor.ports import Now as Now
from dk_results.completion_processor.ports import PresenceOracle as PresenceOracle
from dk_results.completion_processor.processor import CompletionProcessor as CompletionProcessor
from dk_results.completion_processor.soft_finish import _canonical_vips as _canonical_vips
from dk_results.completion_processor.soft_finish import _soft_finish_eligible as _soft_finish_eligible
from dk_results.completion_processor.soft_finish import _soft_finish_event_key as _soft_finish_event_key
from dk_results.completion_processor.sync import COMPLETED_STATUSES as COMPLETED_STATUSES
