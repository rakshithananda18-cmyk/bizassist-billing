"""
tests/test_cloud_token_refresh.py
=================================
The stored cloud token is a normal 24 h access token that used to be minted ONLY
at login. That was survivable while it merely backed background sync — a lapsed
token just paused the backup. It stopped being survivable when the B2B proxy
(routes/b2b_proxy.py) started depending on it: B2B writes would begin failing
every 24 hours until the owner happened to log in again while online.

`sync_worker.ensure_fresh_cloud_token` slides it forward via the cloud's
`POST /auth/refresh` before it expires. These tests pin the decision rules —
when to renew, when to leave it alone, and how each failure mode degrades.
"""
import os
import sys
from datetime import timedelta

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_bizassist.db")

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

import jwt
import pytest

import services.sync_worker as sw
from services.dates import utc_now

BID = 987654


def _token(expires_in: timedelta, secret="a-different-secret-than-local") -> str:
    """A token signed with a secret this backend does NOT share — exactly the
    real situation, since the cloud signs with its own JWT_SECRET."""
    return jwt.encode(
        {"id": BID, "user_id": BID, "exp": utc_now() + expires_in},
        secret,
        algorithm="HS256",
    )


@pytest.fixture(autouse=True)
def _clean_token_state():
    sw._REFRESH_BACKOFF.pop(BID, None)
    m = sw._load_token_map()
    m.pop(str(BID), None)
    sw._save_token_map(m)
    yield
    sw._REFRESH_BACKOFF.pop(BID, None)
    m = sw._load_token_map()
    m.pop(str(BID), None)
    sw._save_token_map(m)


# ── Reading expiry ──────────────────────────────────────────────────────────

def test_expiry_is_read_without_verifying_the_signature():
    """The cloud signs with its own secret, which a packaged local install does
    NOT share. Verifying here would fail on exactly the installs that most need
    the refresh."""
    exp = sw._token_expiry(_token(timedelta(hours=10)))
    assert exp is not None
    remaining = exp - utc_now()
    assert timedelta(hours=9) < remaining < timedelta(hours=11)


def test_garbage_token_has_no_expiry_and_does_not_raise():
    assert sw._token_expiry("not-a-jwt") is None
    assert sw._token_expiry("") is None


# ── When to renew ───────────────────────────────────────────────────────────

def test_a_comfortably_valid_token_is_left_alone(monkeypatch):
    """No network call at all in the steady state — this runs on every tick."""
    tok = _token(timedelta(hours=20))
    sw.store_cloud_token(BID, tok)

    def _boom(*a, **k):
        raise AssertionError("must not call the network for a fresh token")

    monkeypatch.setattr(sw.httpx, "post", _boom)
    assert sw.ensure_fresh_cloud_token(BID) == tok


def test_a_token_near_expiry_is_renewed(monkeypatch):
    sw.store_cloud_token(BID, _token(timedelta(hours=2)))
    fresh = _token(timedelta(hours=24))

    class _Resp:
        status_code = 200
        def json(self): return {"token": fresh}

    monkeypatch.setattr(sw.httpx, "post", lambda *a, **k: _Resp())

    assert sw.ensure_fresh_cloud_token(BID) == fresh
    assert sw._get_cloud_token(BID) == fresh, "the renewed token must be persisted"


def test_no_stored_token_is_a_no_op(monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("nothing to refresh — must not call the network")

    monkeypatch.setattr(sw.httpx, "post", _boom)
    assert sw.ensure_fresh_cloud_token(BID) is None


# ── Failure modes ───────────────────────────────────────────────────────────

def test_offline_keeps_the_existing_token_and_backs_off(monkeypatch):
    """A dead network must not mean one refresh POST per scheduler tick, and it
    must not throw away a token that may still have hours left on it."""
    tok = _token(timedelta(hours=2))
    sw.store_cloud_token(BID, tok)

    def _offline(*a, **k):
        raise OSError("network is unreachable")

    monkeypatch.setattr(sw.httpx, "post", _offline)

    assert sw.ensure_fresh_cloud_token(BID) == tok
    assert BID in sw._REFRESH_BACKOFF

    # Second call inside the backoff window makes no further attempt.
    def _boom(*a, **k):
        raise AssertionError("should be inside the backoff window")

    monkeypatch.setattr(sw.httpx, "post", _boom)
    assert sw.ensure_fresh_cloud_token(BID) == tok


def test_a_rejected_token_is_dropped(monkeypatch):
    """401 means already expired or revoked server-side. Nothing to salvage —
    stop presenting a dead credential and wait for the next online login."""
    sw.store_cloud_token(BID, _token(timedelta(hours=1)))

    class _Resp:
        status_code = 401
        def json(self): return {}

    monkeypatch.setattr(sw.httpx, "post", lambda *a, **k: _Resp())

    assert sw.ensure_fresh_cloud_token(BID) is None
    assert sw._get_cloud_token(BID) is None


def test_a_server_error_keeps_the_current_token(monkeypatch):
    """A 500 upstream is transient — the token we hold may still be usable."""
    tok = _token(timedelta(hours=2))
    sw.store_cloud_token(BID, tok)

    class _Resp:
        status_code = 500
        def json(self): return {}

    monkeypatch.setattr(sw.httpx, "post", lambda *a, **k: _Resp())

    assert sw.ensure_fresh_cloud_token(BID) == tok
    assert sw._get_cloud_token(BID) == tok


def test_a_200_without_a_token_is_treated_as_a_failure(monkeypatch):
    tok = _token(timedelta(hours=2))
    sw.store_cloud_token(BID, tok)

    class _Resp:
        status_code = 200
        def json(self): return {"unexpected": "shape"}

    monkeypatch.setattr(sw.httpx, "post", lambda *a, **k: _Resp())

    assert sw.ensure_fresh_cloud_token(BID) == tok
    assert BID in sw._REFRESH_BACKOFF
