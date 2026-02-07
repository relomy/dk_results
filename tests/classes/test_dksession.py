import pickle

from requests.cookies import RequestsCookieJar

from classes import dksession as dksession_module


def test_dksession_init_and_get_session(monkeypatch):
    jar = RequestsCookieJar()
    jar.set("a", "1", domain="example.com", path="/", expires=1)

    monkeypatch.setattr(dksession_module, "get_dk_cookies", lambda: ({}, jar))

    class FakeSession:
        def __init__(self):
            self.cookies = RequestsCookieJar()

    monkeypatch.setattr(dksession_module.requests, "Session", lambda: FakeSession())

    session = dksession_module.DkSession()
    assert session.get_session() is session.session


def test_cj_from_pickle_missing(tmp_path):
    session = dksession_module.DkSession.__new__(dksession_module.DkSession)
    assert session.cj_from_pickle(str(tmp_path / "missing.pkl")) is None


def test_setup_session_clears_existing_cookie(monkeypatch):
    jar = RequestsCookieJar()
    jar.set("dup", "1", domain="example.com", path="/", expires=1)

    class FakeSession:
        def __init__(self):
            self.cookies = RequestsCookieJar()
            self.cookies.set("dup", "old", domain="example.com", path="/")

    monkeypatch.setattr(dksession_module.requests, "Session", lambda: FakeSession())

    session = dksession_module.DkSession.__new__(dksession_module.DkSession)
    result = session.setup_session(jar)

    assert jar.get("dup") is None
    assert result.cookies.get("dup") == "old"


def test_cj_from_pickle_loads(tmp_path):
    jar = RequestsCookieJar()
    jar.set("a", "1", domain="example.com", path="/")
    path = tmp_path / "cookies.pkl"
    with open(path, "wb") as f:
        pickle.dump(jar, f)

    session = dksession_module.DkSession.__new__(dksession_module.DkSession)
    loaded = session.cj_from_pickle(str(path))

    assert loaded is not None
    assert loaded.get("a") == "1"


def test_setup_session_skips_cookie_without_expires(monkeypatch):
    jar = RequestsCookieJar()
    jar.set("noexp", "1", domain="example.com", path="/")

    class FakeSession:
        def __init__(self):
            self.cookies = RequestsCookieJar()

    monkeypatch.setattr(dksession_module.requests, "Session", lambda: FakeSession())

    session = dksession_module.DkSession.__new__(dksession_module.DkSession)
    result = session.setup_session(jar)

    assert result.cookies.get("noexp") == "1"
