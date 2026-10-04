"""Contract for `contest.vip_lineups` rows and their `players_live` slots.

Locked slots carrying no player key, salary or live state is a semantic check a
type cannot express; the hand-written validator enforces it.
"""

from __future__ import annotations

from pydantic import StrictBool, StrictFloat, StrictInt, StrictStr

from dk_results.services.snapshot_v3.models.base import ContractModel, omittable
from dk_results.services.snapshot_v3.models.names import TrimmedName
from dk_results.services.snapshot_v3.models.numbers import NonEmptyStr


class VipLineupSlot(ContractModel):
    """One roster slot in a VIP's `players_live`.

    A revealed player carries `player_key` when resolvable, `salary` when known
    and `is_live`. A locked slot (a player DraftKings has not revealed) is
    `{slot, player_name: "LOCKED 🔒", is_locked: true}` and carries none of those.
    """

    slot: NonEmptyStr
    player_name: TrimmedName
    player_key: StrictStr = omittable()
    salary: StrictInt = omittable()
    is_live: StrictBool = omittable()
    is_locked: StrictBool = omittable()


class VipLineupRow(ContractModel):
    """One tracked VIP's lineup in `contest.vip_lineups`.

    Every field is omitted when the source cannot supply it; none is ever null.
    """

    display_name: StrictStr = omittable()
    entry_key: StrictStr = omittable()
    vip_entry_key: StrictStr = omittable()
    rank: StrictInt = omittable()
    points: StrictFloat = omittable()
    pmr: StrictFloat = omittable()
    players_live: list[VipLineupSlot] = omittable()
