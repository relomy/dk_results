"""Lobby contest payload builder shared by the dkcontests test files."""

import datetime


def _contest_payload(
    dk_id: int,
    *,
    entries: int = 200,
    fee: int = 25,
    start_dt: datetime.datetime | None = None,
):
    start_dt = start_dt or datetime.datetime.fromtimestamp(1700000000)
    return {
        "sd": str(int(start_dt.timestamp() * 1000)),
        "n": f"Contest {dk_id}",
        "id": dk_id,
        "dg": 10,
        "po": 0,
        "m": entries,
        "a": fee,
        "ec": 0,
        "mec": 1,
        "attr": {"IsDoubleUp": True, "IsGuaranteed": True},
        "gameType": "Classic",
        "gameTypeId": 1,
    }
