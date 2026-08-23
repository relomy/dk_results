import pickle

from requests.cookies import RequestsCookieJar

from dk_results.draftkings import cookies as cookies_module


def test_get_rookie_cookies_pi_path(monkeypatch):
    monkeypatch.setenv("DK_PLATFORM", "pi")
    monkeypatch.setenv("COOKIES_DB_PATH", "/tmp/chrome.db")

    captured = {}

    def fake_chromium_based(db_path=None, domains=None):
        captured["db_path"] = db_path
        captured["domains"] = domains
        return [{"name": "a", "value": "1"}]

    monkeypatch.setattr(cookies_module, "chromium_based", fake_chromium_based)
    monkeypatch.setattr(cookies_module, "chrome", lambda domains=None: [])

    cookies = cookies_module.get_rookie_cookies()
    assert cookies == [{"name": "a", "value": "1"}]
    assert captured["db_path"] == "/tmp/chrome.db"


def test_get_rookie_cookies_fallback(monkeypatch):
    monkeypatch.setenv("DK_PLATFORM", "mac")
    monkeypatch.delenv("COOKIES_DB_PATH", raising=False)

    monkeypatch.setattr(cookies_module, "chromium_based", lambda **_kwargs: [])
    monkeypatch.setattr(
        cookies_module,
        "chrome",
        lambda domains=None: [{"name": "b", "value": "2"}],
    )

    cookies = cookies_module.get_rookie_cookies(["example.com"])
    assert cookies == [{"name": "b", "value": "2"}]


def test_cookies_to_dict_and_jar():
    cookies = [{"name": "a", "value": "1", "domain": "example.com", "path": "/"}]
    assert cookies_module.cookies_to_dict(cookies) == {"a": "1"}

    jar = cookies_module.cookies_to_jar(cookies)
    assert isinstance(jar, RequestsCookieJar)
    assert jar.get("a") == "1"


def test_load_cookies_from_pickle_missing(tmp_path):
    assert cookies_module.load_cookies_from_pickle(str(tmp_path / "missing.pkl")) is None


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
    monkeypatch.setattr(cookies_module, "get_rookie_cookies", lambda *_args, **_kwargs: [])

    cookie_dict, jar = cookies_module.get_dk_cookies(use_pickle=True)
    assert cookie_dict == {"a": "1"}
    assert jar.get("a") == "1"


def test_get_dk_cookies_falls_back_and_saves(monkeypatch):
    monkeypatch.setattr(cookies_module, "load_cookies_from_pickle", lambda: None)
    monkeypatch.setattr(
        cookies_module,
        "get_rookie_cookies",
        lambda *_args, **_kwargs: [{"name": "a", "value": "1", "domain": "example.com", "path": "/"}],
    )

    saved = {}

    def fake_save(cookies, filename=cookies_module.PICKLE_FILE):
        saved["cookies"] = cookies

    monkeypatch.setattr(cookies_module, "save_cookies_to_pickle", fake_save)

    cookie_dict, jar = cookies_module.get_dk_cookies(use_pickle=True)
    assert cookie_dict == {"a": "1"}
    assert saved["cookies"] == [{"name": "a", "value": "1", "domain": "example.com", "path": "/"}]
