import pytest
from classes.contest import Contest
from classes.contestdatabase import ContestDatabase
from dfs_common import state

from dk_results.cli.find_new_double_ups import _upsert_contests


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


def test_contests_upsert_writes_shared_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DFS_STATE_DIR", str(tmp_path))
    contest = Contest(_payload(101), "GOLF")
    _upsert_contests([contest])

    db = ContestDatabase(str(state.contests_db_path()))
    db.create_table()
    try:
        row = db.get_live_contest("GOLF", entry_fee=25)
    finally:
        db.close()

    assert row is not None
    assert row[0] == 101


def test_contests_db_path_requires_env(monkeypatch):
    monkeypatch.delenv("DFS_STATE_DIR", raising=False)
    with pytest.raises(RuntimeError, match="DFS_STATE_DIR"):
        state.contests_db_path()


def test_contests_db_path_logs_info(tmp_path, monkeypatch, caplog):
    monkeypatch.setenv("DFS_STATE_DIR", str(tmp_path))
    caplog.set_level("INFO")
    path = state.contests_db_path()
    assert path == tmp_path / "contests.db"
    assert "Contests DB path is" in caplog.text
    assert str(path) in caplog.text
    assert "Using contests DB at" not in caplog.text


def test_upsert_contests_uses_state_path_once(monkeypatch):
    contest = Contest(_payload(202), "NBA")
    captured = {"db_path": None, "calls": 0}

    def fake_db_path():
        return "/tmp/contests.db"

    def fake_upsert(db_path, rows):
        captured["db_path"] = db_path
        captured["calls"] += 1
        assert rows

    monkeypatch.setattr("dk_results.cli.find_new_double_ups.state.contests_db_path", fake_db_path)
    monkeypatch.setattr("dk_results.cli.find_new_double_ups.contests.upsert_contests", fake_upsert)

    _upsert_contests([contest])

    assert captured == {"db_path": "/tmp/contests.db", "calls": 1}
