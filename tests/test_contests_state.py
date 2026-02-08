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


def test_contests_db_path_does_not_log_info(tmp_path, monkeypatch, caplog):
    monkeypatch.setenv("DFS_STATE_DIR", str(tmp_path))
    caplog.set_level("INFO")
    path = contests_state.contests_db_path()
    assert path == tmp_path / "contests.db"
    assert "Contests DB path is" in caplog.text
    assert str(path) in caplog.text
    assert "Using contests DB at" not in caplog.text


def test_upsert_contests_uses_ensured_schema_path_once(monkeypatch):
    contest = Contest(_payload(202), "NBA")
    captured = {"db_path": None, "calls": 0}

    def fake_ensure_schema():
        return "/tmp/contests.db"

    def fake_upsert(db_path, rows):
        captured["db_path"] = db_path
        captured["calls"] += 1
        assert rows

    monkeypatch.setattr(contests_state, "ensure_schema", fake_ensure_schema)
    monkeypatch.setattr(contests_state.contests, "upsert_contests", fake_upsert)

    contests_state.upsert_contests([contest])

    assert captured == {"db_path": "/tmp/contests.db", "calls": 1}
