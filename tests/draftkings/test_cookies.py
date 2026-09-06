import os
import pickle
import runpy
from http.cookiejar import Cookie

import pytest
from requests.cookies import RequestsCookieJar

from dk_results.draftkings import cookies as cookies_module


def test_importing_cookies_does_not_load_dotenv(monkeypatch):
    calls = {"dotenv": 0}
    monkeypatch.setattr(
        "dotenv.load_dotenv",
        lambda *_args, **_kwargs: calls.__setitem__("dotenv", calls["dotenv"] + 1),
    )

    runpy.run_module("dk_results.draftkings.cookies", run_name="cookies_import_probe")

    assert calls == {"dotenv": 0}


def test_get_browser_cookies_pi_path(monkeypatch):
    monkeypatch.setenv("DK_PLATFORM", "pi")
    monkeypatch.setenv("COOKIES_DB_PATH", "/tmp/chromium/Profile 1/Cookies")

    captured = {}

    def fake_run(args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        cookie_path = args[args.index("--cookies") + 1]
        with open(cookie_path, "w", encoding="utf-8") as fp:
            fp.write("# Netscape HTTP Cookie File\n")
            fp.write(".draftkings.com\tTRUE\t/\tTRUE\t0\ta\t1\n")
        return type("Result", (), {"returncode": 0})()

    monkeypatch.setattr(cookies_module.subprocess, "run", fake_run)

    cookies = cookies_module.get_browser_cookies()
    assert cookies == [
        {
            "name": "a",
            "value": "1",
            "domain": ".draftkings.com",
            "path": "/",
            "expires": None,
            "secure": True,
        }
    ]
    assert captured["args"][:3] == [cookies_module.sys.executable, "-m", "yt_dlp"]
    assert "chromium:/tmp/chromium/Profile 1" in captured["args"]


def test_get_browser_cookies_fallback(monkeypatch):
    monkeypatch.setenv("DK_PLATFORM", "mac")
    monkeypatch.delenv("COOKIES_DB_PATH", raising=False)

    def fake_run(args, **_kwargs):
        cookie_path = args[args.index("--cookies") + 1]
        with open(cookie_path, "w", encoding="utf-8") as fp:
            fp.write("# Netscape HTTP Cookie File\n")
            fp.write(".example.com\tTRUE\t/\tTRUE\t0\tb\t2\n")
        return type("Result", (), {"returncode": 0})()

    monkeypatch.setattr(cookies_module.subprocess, "run", fake_run)

    cookies = cookies_module.get_browser_cookies(["example.com"])
    assert cookies == [
        {
            "name": "b",
            "value": "2",
            "domain": ".example.com",
            "path": "/",
            "expires": None,
            "secure": True,
        }
    ]


@pytest.mark.parametrize(
    ("stderr", "message"),
    [
        ("ERROR: could not find chromium cookies database", "browser cookie database was not found"),
        ("ERROR: cannot decrypt browser cookies; keyring unavailable", "browser cookies could not be decrypted"),
    ],
)
def test_get_browser_cookies_reports_actionable_export_failure(monkeypatch, stderr, message):
    result = type("Result", (), {"returncode": 1, "stderr": stderr})()

    monkeypatch.setattr(cookies_module.subprocess, "run", lambda *args, **kwargs: result)

    with pytest.raises(RuntimeError, match=message):
        cookies_module.get_browser_cookies()


def test_cookie_to_dict():
    cookie = Cookie(
        version=0,
        name="a",
        value="1",
        port=None,
        port_specified=False,
        domain=".example.com",
        domain_specified=True,
        domain_initial_dot=True,
        path="/",
        path_specified=True,
        secure=True,
        expires=None,
        discard=True,
        comment=None,
        comment_url=None,
        rest={},
        rfc2109=False,
    )
    assert cookies_module._cookie_to_dict(cookie) == {
        "name": "a",
        "value": "1",
        "domain": ".example.com",
        "path": "/",
        "expires": None,
        "secure": True,
    }


def test_cookies_to_dict_and_jar():
    cookies = [{"name": "a", "value": "1", "domain": "example.com", "path": "/"}]
    assert cookies_module.cookies_to_dict(cookies) == {"a": "1"}

    jar = cookies_module.cookies_to_jar(cookies)
    assert isinstance(jar, RequestsCookieJar)
    assert jar.get("a") == "1"


def test_load_cookies_from_pickle_missing(tmp_path):
    assert cookies_module.load_cookies_from_pickle(str(tmp_path / "missing.pkl")) is None


def test_load_cookies_from_pickle_stale_is_treated_as_missing(tmp_path):
    path = tmp_path / "cookies.pkl"
    with path.open("wb") as f:
        pickle.dump(RequestsCookieJar(), f)

    old_time = path.stat().st_mtime - 1000
    os.utime(path, (old_time, old_time))

    assert cookies_module.load_cookies_from_pickle(str(path), max_age_seconds=900) is None


def test_load_cookies_from_pickle_within_max_age_is_loaded(tmp_path):
    jar = RequestsCookieJar()
    jar.set("a", "1", domain="example.com", path="/")
    path = tmp_path / "cookies.pkl"
    with path.open("wb") as f:
        pickle.dump(jar, f)

    loaded = cookies_module.load_cookies_from_pickle(str(path), max_age_seconds=900)
    assert loaded is not None
    assert loaded.get("a") == "1"


def test_load_cookies_from_pickle_invalid(tmp_path, monkeypatch):
    path = tmp_path / "cookies.pkl"
    path.write_bytes(b"not-a-pickle")

    def boom(_fp):
        raise ValueError("bad")

    monkeypatch.setattr(cookies_module.pickle, "load", boom)
    assert cookies_module.load_cookies_from_pickle(str(path)) is None


def test_save_cookies_to_pickle_error(monkeypatch):
    def boom(*_args, **_kwargs):
        raise OSError("nope")

    monkeypatch.setattr("builtins.open", boom)
    cookies_module.save_cookies_to_pickle([{"name": "a", "value": "1"}])


def test_save_cookies_to_pickle_success(tmp_path):
    cookies = [{"name": "a", "value": "1", "domain": "example.com", "path": "/"}]
    path = tmp_path / "cookies.pkl"

    cookies_module.save_cookies_to_pickle(cookies, filename=str(path))

    assert path.exists()
    with open(path, "rb") as f:
        assert pickle.load(f) == cookies


def test_get_dk_cookies_uses_pickle(monkeypatch):
    monkeypatch.setattr(
        cookies_module,
        "load_cookies_from_pickle",
        lambda: [{"name": "a", "value": "1", "domain": "example.com", "path": "/"}],
    )
    monkeypatch.setattr(cookies_module, "get_browser_cookies", lambda *_args, **_kwargs: [])

    cookie_dict, jar = cookies_module.get_dk_cookies(use_pickle=True)
    assert cookie_dict == {"a": "1"}
    assert jar.get("a") == "1"


def test_get_dk_cookies_falls_back_and_saves(monkeypatch):
    monkeypatch.setattr(cookies_module, "load_cookies_from_pickle", lambda: None)
    monkeypatch.setattr(
        cookies_module,
        "get_browser_cookies",
        lambda *_args, **_kwargs: [{"name": "a", "value": "1", "domain": "example.com", "path": "/"}],
    )

    saved = {}

    def fake_save(cookies, filename=cookies_module.PICKLE_FILE):
        saved["cookies"] = cookies

    monkeypatch.setattr(cookies_module, "save_cookies_to_pickle", fake_save)

    cookie_dict, jar = cookies_module.get_dk_cookies(use_pickle=True)
    assert cookie_dict == {"a": "1"}
    assert saved["cookies"] == [{"name": "a", "value": "1", "domain": "example.com", "path": "/"}]
