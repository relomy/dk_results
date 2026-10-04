"""Contract for `contest.vip_lineups` rows and their `players_live` slots.

Player names with no leading or trailing whitespace, and locked slots carrying
no player key, salary or live state, are semantic checks a type cannot express;
the hand-written validator enforces them.
"""

from __future__ import annotations

from pydantic import StrictBool, StrictFloat, StrictInt, StrictStr

from dk_results.services.snapshot_v3.models.base import ContractModel, omittable


class VipLineupSlot(ContractModel):
    """One roster slot in a VIP's `players_live`.

    A revealed player carries `player_key` when resolvable, `salary` when known
    and `is_live`. A locked slot (a player DraftKings has not revealed) is
    `{slot, player_name: "LOCKED 🔒", is_locked: true}` and carries none of those.
    """

    slot: StrictStr
    player_name: StrictStr
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
