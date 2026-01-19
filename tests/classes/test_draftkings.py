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

    def get(self, *_args, **_kwargs):
        return self._response


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
