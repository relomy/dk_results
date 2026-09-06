import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
PKG_ROOT = SRC_ROOT / "dk_results"

for path in (REPO_ROOT, SRC_ROOT, PKG_ROOT):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)


class _StubLobbyResponse:
    """Stand-in for a requests.Response carrying a fixed JSON payload."""

    status_code = 200

    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


@pytest.fixture
def anonymous_lobby(monkeypatch):
    """Exercise the real DraftKings client on an unauthenticated lobby read.

    Trips (AssertionError) if the path constructs ``AuthSession`` or calls
    ``get_dk_cookies`` — the yt-dlp cookie extraction that regressed
    ``dkcontests.py`` latency (ADR-0009, #102). Returns a ``serve(payload)``
    callable that stubs ``Session.get`` so no network I/O happens; the real
    ``DraftKings.__init__`` / session construction still runs.
    """
    from dk_results.draftkings import client as dk_client_module
    from dk_results.draftkings import session as dk_session_module

    def _forbid(name):
        def _boom(*_args, **_kwargs):
            raise AssertionError(f"lobby reads must not reach {name} (ADR-0009)")

        return _boom

    monkeypatch.setattr(dk_client_module, "AuthSession", _forbid("AuthSession"))
    monkeypatch.setattr(dk_session_module, "get_dk_cookies", _forbid("get_dk_cookies"))

    def serve(payload):
        monkeypatch.setattr(
            "requests.sessions.Session.get",
            lambda self, *args, **kwargs: _StubLobbyResponse(payload),
        )

    return serve
