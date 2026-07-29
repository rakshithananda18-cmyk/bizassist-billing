"""
tests/test_b2b_proxy.py
=======================
Guards the routing and fail-safe decisions of the local→cloud B2B proxy.

The proxy exists because a session token is only valid on the backend that
issued it. An earlier revision had the BROWSER call the cloud directly for B2B;
the cloud then resolved the local user id against its own users table, where the
same integer is a different business, and one tenant saw another's BizID. These
tests pin down the rules that make that impossible to reintroduce.

Pure unit tests over the decision helpers — no network, no TestClient — so they
stay fast and can't flake on connectivity.
"""
import os
import sys

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_bizassist.db")

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

import pytest

from routes import b2b_proxy


# ── Which paths go upstream ─────────────────────────────────────────────────

@pytest.mark.parametrize("path", [
    "/connections",
    "/connections/connections",
    "/connections/connections/connect",
    "/connections/connections/7/approve",
    "/connections/orders",
    "/connections/orders/12/status",
    "/connections/catalog/BA-ABC123",
])
def test_b2b_paths_are_proxied(path):
    """Everything under /connections describes or reads ANOTHER business, which
    by definition is not in this database."""
    assert b2b_proxy._should_proxy(path) is True


def test_bizid_lookup_of_another_business_is_proxied():
    assert b2b_proxy._should_proxy("/bizid/BA-ABC123") is True


def test_own_bizid_is_never_proxied():
    """The bare /bizid is the caller's OWN identity and the local DB answers it
    correctly. Proxying it is what made the workspace hang on "Loading…" when
    the cloud had no matching local user id."""
    assert b2b_proxy._should_proxy("/bizid") is False
    assert b2b_proxy._is_bizid_lookup("/bizid") is False
    assert b2b_proxy._is_bizid_lookup("/bizid/") is False


@pytest.mark.parametrize("path", [
    "/sales", "/login", "/api/sync/push", "/bizid",
    "/connectionsomething",          # prefix must not match a longer word
    "/business/billing-profile",
])
def test_non_b2b_paths_are_left_alone(path):
    assert b2b_proxy._should_proxy(path) is False


# ── Read vs write fail-safe ─────────────────────────────────────────────────

def test_reads_may_fall_back_offline_but_writes_may_not():
    """A B2B write that lands only in the local DB is invisible to the
    counterparty forever — pull-only sync will never carry it up. So writes fail
    loudly offline, while reads quietly serve the local mirror."""
    assert "GET" in b2b_proxy._READ_METHODS
    assert "HEAD" in b2b_proxy._READ_METHODS
    for verb in ("POST", "PUT", "PATCH", "DELETE"):
        assert verb not in b2b_proxy._READ_METHODS


def test_successful_b2b_writes_trigger_a_local_projection_pull():
    assert b2b_proxy._should_pull_after_b2b_write("POST", 200) is True
    assert b2b_proxy._should_pull_after_b2b_write("PATCH", 204) is True
    assert b2b_proxy._should_pull_after_b2b_write("GET", 200) is False
    assert b2b_proxy._should_pull_after_b2b_write("POST", 400) is False
    assert b2b_proxy._should_pull_after_b2b_write("POST", 503) is False


# ── Identity resolution ─────────────────────────────────────────────────────

def _bearer(payload):
    from services.auth import create_access_token

    class _Req:
        def __init__(self, token):
            self.headers = {"authorization": f"Bearer {token}"} if token else {}

    return _Req(create_access_token(payload) if payload is not None else None)


def test_business_id_comes_from_the_local_token():
    req = _bearer({"id": 42, "user_id": 42, "username": "u", "public_id": "BA-X", "role": "enterprise"})
    assert b2b_proxy._business_id_from(req) == 42


def test_staff_token_resolves_to_the_OWNER_business():
    """B2B is always scoped to the owner business, never the individual cashier —
    otherwise a staff login would see an empty (or wrong) network."""
    req = _bearer({
        "id": 99, "user_id": 99, "parent_business_id": 42,
        "username": "cashier", "public_id": "BA-X", "role": "cashier",
    })
    assert b2b_proxy._business_id_from(req) == 42


def test_missing_or_garbage_auth_resolves_to_none():
    class _Req:
        def __init__(self, headers):
            self.headers = headers

    assert b2b_proxy._business_id_from(_Req({})) is None
    assert b2b_proxy._business_id_from(_Req({"authorization": "Basic abc"})) is None
    assert b2b_proxy._business_id_from(_Req({"authorization": "Bearer not-a-jwt"})) is None


# ── Response framing ────────────────────────────────────────────────────────

def test_upstream_framing_headers_are_not_echoed():
    """httpx has already decoded the body, so copying the upstream's
    content-length / content-encoding would misdescribe what we send on."""
    for h in ("content-length", "content-encoding", "transfer-encoding"):
        assert h in b2b_proxy._SKIP_RESPONSE_HEADERS


def test_proxy_is_inert_on_the_cloud_deployment(monkeypatch):
    """On Postgres (the cloud) the proxy must do nothing — otherwise the cloud
    would forward requests to itself in a loop."""
    class _Dialect:
        name = "postgresql"

    class _Engine:
        dialect = _Dialect()

    monkeypatch.setattr(b2b_proxy, "engine", _Engine())
    assert b2b_proxy._is_local_backend() is False


def test_proxy_is_active_on_a_local_sqlite_install(monkeypatch):
    class _Dialect:
        name = "sqlite"

    class _Engine:
        dialect = _Dialect()

    monkeypatch.setattr(b2b_proxy, "engine", _Engine())
    assert b2b_proxy._is_local_backend() is True
