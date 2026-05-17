from __future__ import annotations

import logging
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from classes.draftkings import Draftkings
from requests.cookies import RequestsCookieJar
from requests.sessions import Session


class _FakeResponse:
    def __init__(self, *, content: bytes, headers: dict[str, str]):
        self.content = content
        self.headers = headers
        self.status_code = 200
        self.url = "https://example.test/contest/export"
        self.text = content.decode("utf-8", errors="ignore") if isinstance(content, bytes) else str(content)


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


def test_download_salary_csv_creates_directory(tmp_path):
    salary_path = tmp_path / "salary" / "GOLF" / "DKSalaries_GOLF_Saturday.csv"
    response = _FakeResponse(content=b"name,value\n", headers={"Content-Type": "text/csv"})

    class SalarySession:
        def __init__(self, response: _FakeResponse):
            self._response = response

        def get(self, *args, **kwargs):
            return self._response

    dk = Draftkings(session=SalarySession(response))
    dk.download_salary_csv("GOLF", 1, str(salary_path))

    assert salary_path.exists()
    assert salary_path.read_bytes() == b"name,value\n"


class _Response:
    def __init__(self, *, json_data=None, status_code=200, headers=None, content=b""):
        self._json = json_data or {}
        self.status_code = status_code
        self.headers = headers or {}
        self.content = content
        self.url = "https://example.test"
        self.text = content.decode("utf-8", errors="ignore") if isinstance(content, bytes) else str(content)

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError("bad")

    def json(self):
        return self._json


class _Session:
    def __init__(self, response: _Response):
        self._response = response
        self.headers = {"X": "Y"}
        self.cookies = _Cookies()
        self.last = None

    def get(self, url, timeout=None):
        self.last = (url, timeout)
        return self._response


class _Cookies:
    def __init__(self):
        self._items = [SimpleNamespace(name="a", value="1", domain="example.com", path="/")]

    def get_dict(self):
        raise RuntimeError("boom")

    def __iter__(self):
        return iter(self._items)


def test_clone_auth_to_fallbacks_on_cookie_error():
    response = _Response(json_data={})
    session = _Session(response)
    dk = Draftkings(session=session)

    target = Session()
    dk.clone_auth_to(target)

    assert target.headers["X"] == "Y"
    assert target.cookies.get("a") == "1"


def test_get_leaderboard_uses_timeout_and_session():
    response = _Response(json_data={"ok": True})
    session = _Session(response)
    dk = Draftkings(session=session)

    assert dk.get_leaderboard(123) == {"ok": True}
    assert "leaderboards" in session.last[0]


def test_get_entry_uses_session():
    response = _Response(json_data={"entries": []})
    session = _Session(response)
    dk = Draftkings(session=session)

    assert dk.get_entry(1, "abc") == {"entries": []}
    assert "entries" in session.last[0]


def test_redact_url_for_log_strips_querystring():
    dk = Draftkings(session=_Session(_Response()))
    redacted = dk._redact_url_for_log("https://example.test/path/to/file.csv?token=abc123&sig=xyz#frag")
    assert redacted == "https://example.test/path/to/file.csv"


def test_download_contest_rows_html_returns_none():
    response = _Response(headers={"Content-Type": "text/html"})
    response.url = "https://example.test/contest/export?X-Amz-Security-Token=secret-token&X-Amz-Signature=abcdef123456"
    session = _Session(response)
    dk = Draftkings(session=session)

    assert dk.download_contest_rows(1) is None


def test_download_contest_rows_redacts_signed_url_in_logs(caplog):
    response = _Response(headers={"Content-Type": "text/html"})
    response.url = "https://example.test/contest/export?X-Amz-Security-Token=secret-token&X-Amz-Signature=abcdef123456"
    session = _Session(response)
    dk = Draftkings(session=session)

    with caplog.at_level(logging.DEBUG, logger=dk.logger.name):
        assert dk.download_contest_rows(1) is None

    assert "X-Amz-Security-Token" not in caplog.text
    assert "X-Amz-Signature" not in caplog.text
    assert "url=https://example.test/contest/export" in caplog.text


def test_download_contest_rows_bad_zip_returns_none():
    response = _Response(
        headers={"Content-Type": "application/octet-stream"},
        content=b"not-zip",
    )
    session = _Session(response)
    dk = Draftkings(session=session)

    assert dk.download_contest_rows(1) is None


def test_download_contest_rows_zip_reads_csv(tmp_path):
    import io
    import zipfile

    csv_bytes = b"col1,col2\n1,2\n"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("file.csv", csv_bytes)

    response = _Response(
        headers={"Content-Type": "application/zip"},
        content=buf.getvalue(),
    )
    session = _Session(response)
    dk = Draftkings(session=session)

    rows = dk.download_contest_rows(1, contest_dir=str(tmp_path))
    assert rows == [["col1", "col2"], ["1", "2"]]


def test_download_contest_rows_skips_cookie_dump_error(tmp_path, monkeypatch):
    csv_bytes = b"col1,col2\n1,2\n"
    response = _Response(headers={"Content-Type": "text/csv"}, content=csv_bytes)
    session = _Session(response)
    dk = Draftkings(session=session)

    cookie_dir = tmp_path / "cookies"
    cookie_dir.mkdir()

    rows = dk.download_contest_rows(
        1,
        contest_dir=str(tmp_path),
        cookies_dump_file=str(cookie_dir),
    )
    assert rows == [["col1", "col2"], ["1", "2"]]


def test_download_contest_rows_warns_on_write_error(monkeypatch):
    csv_bytes = b"col1,col2\n1,2\n"
    response = _Response(headers={"Content-Type": "text/csv"}, content=csv_bytes)
    session = _Session(response)
    dk = Draftkings(session=session)

    def boom(*_args, **_kwargs):
        raise OSError("nope")

    monkeypatch.setattr("builtins.open", boom)

    rows = dk.download_contest_rows(1, contest_dir="contests")
    assert rows == [["col1", "col2"], ["1", "2"]]


def test_download_salary_csv_raises_on_non_200(tmp_path):
    response = _Response(status_code=500)
    session = _Session(response)
    dk = Draftkings(session=session)

    with pytest.raises(Exception):
        dk.download_salary_csv("NBA", 123, str(tmp_path / "salary.csv"))


def test_download_salary_csv_writes_file(tmp_path):
    response = _Response(status_code=200, content=b"csv")
    session = _Session(response)
    dk = Draftkings(session=session)

    path = tmp_path / "salary.csv"
    dk.download_salary_csv("NBA", 123, str(path))

    assert path.read_text().strip() == "csv"


def test_clone_auth_to_ignores_cookie_set_errors():
    class SourceCookies:
        def get_dict(self):
            raise RuntimeError("boom")

        def __iter__(self):
            return iter([SimpleNamespace(name="a", value="1", domain="example.com", path="/")])

    class TargetCookies:
        def __init__(self):
            self.calls = 0

        def set(self, *_args, **_kwargs):
            self.calls += 1
            raise RuntimeError("nope")

    class SourceSession:
        def __init__(self):
            self.headers = {"X": "Y"}
            self.cookies = SourceCookies()

    class TargetSession:
        def __init__(self):
            self.headers = {}
            self.cookies = TargetCookies()

    dk = Draftkings(session=SourceSession())
    target = TargetSession()

    dk.clone_auth_to(target)

    assert target.headers["X"] == "Y"
    assert target.cookies.calls == 1


def test_get_contest_detail_uses_session():
    called = {}

    class Response:
        def __init__(self):
            self.status_code = 200

        def raise_for_status(self):
            called["raised"] = True

        def json(self):
            return {"ok": True}

    class Sess:
        def get(self, url, timeout=None):
            called["url"] = url
            called["timeout"] = timeout
            return Response()

    dk = Draftkings(session=Sess())
    assert dk.get_contest_detail(123) == {"ok": True}
    assert "contests/v1/contests/123" in called["url"]
    assert called["raised"] is True


def test_get_lobby_contests_live_uses_url():
    called = {}

    class Response:
        def raise_for_status(self):
            called["raised"] = True

        def json(self):
            return {"ok": True}

    class Sess:
        def get(self, url, timeout=None):
            called["url"] = url
            called["timeout"] = timeout
            return Response()

    dk = Draftkings(session=Sess())
    assert dk.get_lobby_contests("NBA", live=True) == {"ok": True}
    assert "getlivecontests" in called["url"]


def test_download_contest_rows_writes_cookie_dump(tmp_path):
    csv_bytes = b"col1,col2\n1,2\n"
    response = _Response(headers={"Content-Type": "text/csv"}, content=csv_bytes)
    session = _Session(response)
    session.cookies = RequestsCookieJar()
    session.cookies.set("a", "1", domain="example.com", path="/")

    dk = Draftkings(session=session)
    cookie_file = tmp_path / "cookies.pkl"

    dk.download_contest_rows(
        1,
        contest_dir=str(tmp_path),
        cookies_dump_file=str(cookie_file),
    )

    assert cookie_file.exists()


def test_download_contest_rows_empty_zip_returns_none():
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w"):
        pass

    response = _Response(
        headers={"Content-Type": "application/zip"},
        content=buf.getvalue(),
    )
    session = _Session(response)
    dk = Draftkings(session=session)

    assert dk.download_contest_rows(1) is None


def test_download_salary_csv_logs_structured_events(tmp_path, caplog):
    response = _Response(status_code=200, content=b"name,salary\nPlayer A,7000\n")
    session = _Session(response)
    dk = Draftkings(session=session)

    filename = str(tmp_path / "DKSalaries_GOLF_Sunday.csv")
    with caplog.at_level(logging.DEBUG, logger=dk.logger.name):
        dk.download_salary_csv("GOLF", 146727, filename)

    messages = [r.message for r in caplog.records]
    assert any("contest_types" in m and "type_id=9" in m for m in messages)
    assert not any("CONTEST_TYPES" in m for m in messages)
    assert any("salary_write" in m and "DKSalaries_GOLF_Sunday.csv" in m for m in messages)
    assert not any("Writing r.text" in m for m in messages)


def test_download_contest_rows_logs_standings_extract(tmp_path, caplog):
    import io
    import zipfile

    csv_bytes = b"col1,col2\n1,2\n"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("standings.csv", csv_bytes)

    response = _Response(
        headers={"Content-Type": "application/zip"},
        content=buf.getvalue(),
    )
    session = _Session(response)
    dk = Draftkings(session=session)

    with caplog.at_level(logging.DEBUG, logger=dk.logger.name):
        dk.download_contest_rows(123, contest_dir=str(tmp_path))

    messages = [r.message for r in caplog.records]
    assert any("standings_extract" in m for m in messages)
    assert not any(m.startswith("extracted:") for m in messages)
