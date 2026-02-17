from __future__ import annotations

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


def test_normalize_and_lookup_salary():
    dk = Draftkings(session=_Session(_Response()))
    assert dk._normalize_name("José") == "Jose"
    assert dk._normalize_name(123) == ""

    assert dk._lookup_salary("José", {"Jose": 100}) == 100
    assert dk._lookup_salary("", {"Jose": 100}) is None


def test_fetch_user_lineup_worker_missing_entry_key():
    dk = Draftkings(session=_Session(_Response()))
    assert dk._fetch_user_lineup_worker({"userName": "vip"}, 1) is None


def test_fetch_user_lineup_worker_handles_invalid_scores(monkeypatch):
    dk = Draftkings(session=_Session(_Response()))

    def fake_get_entry(_dg, _entry_key, timeout=None, session=None):
        return {
            "entries": [
                {
                    "roster": {
                        "scorecards": [
                            {
                                "displayName": "Player A",
                                "rosterPosition": "RB",
                                "score": "bad",
                                "percentDrafted": 50,
                                "projection": {"realTimeProjection": "bad"},
                            }
                        ]
                    }
                }
            ]
        }

    monkeypatch.setattr(dk, "get_entry", fake_get_entry)

    result = dk._fetch_user_lineup_worker(
        {"entryKey": "abc", "userName": "vip"},
        1,
        {"Player A": 4000},
    )

    assert result is not None
    assert result["players"][0]["value"] == ""
    assert result["players"][0]["rtProj"] == "bad"


def test_get_vip_lineups_with_entries(monkeypatch):
    dk = Draftkings(session=_Session(_Response()))

    monkeypatch.setattr(
        dk,
        "_fetch_user_lineup_worker",
        lambda *_args, **_kwargs: {"user": "vip", "players": []},
    )

    result = dk.get_vip_lineups(
        1,
        2,
        ["vip"],
        vip_entries={"vip": {"entry_key": "abc"}},
    )

    assert result == [{"user": "vip", "players": []}]


def test_get_vip_lineups_handles_worker_exception(monkeypatch):
    dk = Draftkings(session=_Session(_Response()))

    def boom(*_args, **_kwargs):
        raise RuntimeError("bad")

    monkeypatch.setattr(dk, "_fetch_user_lineup_worker", boom)

    result = dk.get_vip_lineups(
        1,
        2,
        ["vip"],
        vip_entries={"vip": {"entry_key": "abc"}},
    )

    assert result == []


def test_download_contest_rows_html_returns_none():
    response = _Response(headers={"Content-Type": "text/html"})
    session = _Session(response)
    dk = Draftkings(session=session)

    assert dk.download_contest_rows(1) is None


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


def test_lookup_salary_blank_and_missing_normalized():
    dk = Draftkings(session=_Session(_Response()))
    assert dk._lookup_salary("   ", {"A": 1}) is None
    assert dk._lookup_salary("José", {"Joe": 1}) is None


def test_fetch_user_lineup_worker_no_entries(monkeypatch):
    dk = Draftkings(session=_Session(_Response()))

    def fake_get_entry(_dg, _entry_key, timeout=None, session=None):
        return {"entries": []}

    monkeypatch.setattr(dk, "get_entry", fake_get_entry)

    assert dk._fetch_user_lineup_worker({"entryKey": "abc"}, 1) is None


def test_get_vip_lineups_skips_empty_entry_key():
    dk = Draftkings(session=_Session(_Response()))
    assert dk.get_vip_lineups(1, 2, ["vip"], vip_entries={"vip": ""}) == []


def test_get_vip_lineups_leaderboard_path(monkeypatch):
    dk = Draftkings(session=_Session(_Response()))

    monkeypatch.setattr(
        dk,
        "get_leaderboard",
        lambda *_args, **_kwargs: {"leaderBoard": [{"userName": "vip"}]},
    )
    monkeypatch.setattr(
        dk,
        "_fetch_user_lineup_worker",
        lambda *_args, **_kwargs: {"user": "vip", "players": []},
    )

    result = dk.get_vip_lineups(1, 2, ["vip"])
    assert result == [{"user": "vip", "players": []}]


def test_get_vip_lineups_result_none(monkeypatch):
    dk = Draftkings(session=_Session(_Response()))
    monkeypatch.setattr(dk, "_fetch_user_lineup_worker", lambda *_args, **_kwargs: None)

    assert dk.get_vip_lineups(1, 2, ["vip"], vip_entries={"vip": "abc"}) == []


def test_get_vip_lineups_error_logs_swallows(monkeypatch):
    dk = Draftkings(session=_Session(_Response()))

    def boom(*_args, **_kwargs):
        raise RuntimeError("bad")

    monkeypatch.setattr(dk, "_fetch_user_lineup_worker", boom)
    monkeypatch.setattr(
        dk.logger,
        "error",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("log")),
    )
    assert dk.get_vip_lineups(1, 2, ["vip"], vip_entries={"vip": "abc"}) == []


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
