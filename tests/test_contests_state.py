import pytest

from classes.contest import Contest
from classes.contestdatabase import ContestDatabase
import contests_state


def _payload(dk_id: int):
    return {
        "sd": "1700000000000",
        "n": "Contest",
        "id": dk_id,
        "dg": 1,
        "po": 1000,
        "m": 200,
        "a": 25,
        "ec": 0,
        "mec": 1,
        "attr": {},
        "gameType": "Classic",
        "gameTypeId": 1,
    }


def test_contests_state_writes_shared_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DFS_STATE_DIR", str(tmp_path))
    contest = Contest(_payload(101), "GOLF")
    contests_state.upsert_contests([contest])

    db = ContestDatabase(str(contests_state.contests_db_path()))
    db.create_table()
    try:
        row = db.get_live_contest("GOLF", entry_fee=25)
    finally:
        db.close()

    assert row is not None
    assert row[0] == 101


def test_contests_state_requires_env(monkeypatch):
    monkeypatch.delenv("DFS_STATE_DIR", raising=False)
    with pytest.raises(RuntimeError, match="DFS_STATE_DIR"):
        contests_state.contests_db_path()
