import pickle

from requests.cookies import RequestsCookieJar

from dk_results.draftkings import session as session_module


class _FakeSession:
    def __init__(self):
        self.cookies = RequestsCookieJar()


def test_auth_session_defers_cookie_fetch_until_get_session(monkeypatch):
    jar = RequestsCookieJar()
    jar.set("a", "1", domain="example.com", path="/", expires=1)
    calls = []

    def fake_get_dk_cookies(**kwargs):
        calls.append(kwargs)
        return {}, jar

    monkeypatch.setattr(session_module, "get_dk_cookies", fake_get_dk_cookies)
    monkeypatch.setattr(session_module.requests, "Session", _FakeSession)

    session = session_module.AuthSession()
    assert session.session is None, "cookies should not be fetched until get_session() is called"

    session.get_session()
    assert calls == [{"use_pickle": True}]


def test_auth_session_get_session_caches_result(monkeypatch):
    jar = RequestsCookieJar()
    monkeypatch.setattr(session_module, "get_dk_cookies", lambda **_kwargs: ({}, jar))
    monkeypatch.setattr(session_module.requests, "Session", _FakeSession)

    session = session_module.AuthSession()
    result = session.get_session()

    assert session.session is result
    assert session.get_session() is result


def test_cj_from_pickle_missing(tmp_path):
    session = session_module.AuthSession.__new__(session_module.AuthSession)
    assert session.cj_from_pickle(str(tmp_path / "missing.pkl")) is None


def test_setup_session_clears_existing_cookie(monkeypatch):
    jar = RequestsCookieJar()
    jar.set("dup", "1", domain="example.com", path="/", expires=1)

    class FakeSession:
        def __init__(self):
            self.cookies = RequestsCookieJar()
            self.cookies.set("dup", "old", domain="example.com", path="/")

    monkeypatch.setattr(session_module.requests, "Session", lambda: FakeSession())

    session = session_module.AuthSession.__new__(session_module.AuthSession)
    result = session.setup_session(jar)

    assert jar.get("dup") is None
    assert result.cookies.get("dup") == "old"


def test_cj_from_pickle_loads(tmp_path):
    jar = RequestsCookieJar()
    jar.set("a", "1", domain="example.com", path="/")
    path = tmp_path / "cookies.pkl"
    with open(path, "wb") as f:
        pickle.dump(jar, f)

    session = session_module.AuthSession.__new__(session_module.AuthSession)
    loaded = session.cj_from_pickle(str(path))

    assert loaded is not None
    assert loaded.get("a") == "1"


def test_setup_session_skips_cookie_without_expires(monkeypatch):
    jar = RequestsCookieJar()
    jar.set("noexp", "1", domain="example.com", path="/")

    class FakeSession:
        def __init__(self):
            self.cookies = RequestsCookieJar()

    monkeypatch.setattr(session_module.requests, "Session", lambda: FakeSession())

    session = session_module.AuthSession.__new__(session_module.AuthSession)
    result = session.setup_session(jar)

    assert result.cookies.get("noexp") == "1"
