from __future__ import annotations

from pathlib import Path
from typing import cast

from requests.sessions import Session

from classes.draftkings import Draftkings


class _FakeResponse:
    def __init__(self, *, content: bytes, headers: dict[str, str]):
        self.content = content
        self.headers = headers
        self.status_code = 200
        self.url = "https://example.test/contest/export"


class _FakeSession:
    def __init__(self, response: _FakeResponse):
        self._response = response
        self.headers = {}
        self.cookies = _FakeCookies()

    def get(self, *_args, **_kwargs):
        return self._response


class _FakeCookies:
    def get_dict(self):
        return {}


def test_download_contest_rows_writes_csv(tmp_path):
    csv_bytes = b"col1,col2\n1,2\n"
    response = _FakeResponse(
        content=csv_bytes,
        headers={"Content-Type": "text/csv"},
    )
    session = cast(Session, _FakeSession(response))
    dk = Draftkings(session=session)

    rows = dk.download_contest_rows(
        contest_id=123,
        contest_dir=str(tmp_path),
    )

    expected_path = Path(tmp_path) / "contest-standings-123.csv"
    assert expected_path.exists()
    assert expected_path.read_bytes() == csv_bytes
    assert rows == [["col1", "col2"], ["1", "2"]]


def test_fetch_user_lineup_worker_adds_salary_total(monkeypatch):
    dk = Draftkings(session=_FakeSession(_FakeResponse(content=b"", headers={})))

    def fake_get_entry(_dg, _entry_key, timeout=None, session=None):
        return {
            "entries": [
                {
                    "roster": {
                        "scorecards": [
                            {
                                "displayName": "Player A",
                                "rosterPosition": "RB",
                                "score": "10",
                                "percentDrafted": 50,
                                "projection": {},
                            },
                            {
                                "displayName": "Player B",
                                "rosterPosition": "WR",
                                "score": "5",
                                "percentDrafted": 20,
                                "projection": {},
                            },
                        ]
                    }
                }
            ]
        }

    monkeypatch.setattr(dk, "get_entry", fake_get_entry)

    result = dk._fetch_user_lineup_worker(
        {"entryKey": "abc", "userName": "vip"}, 1, {"Player A": 4000, "Player B": 3500}
    )

    assert result is not None
    assert result["salary"] == 7500
