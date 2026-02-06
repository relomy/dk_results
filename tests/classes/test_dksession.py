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
