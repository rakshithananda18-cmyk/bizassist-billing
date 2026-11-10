# Observed counterexamples on the unfixed code (task 1.1):
#   expired token, GET /profile and GET /settings -> 401 "Signature has expired"
#     without WWW-Authenticate.
#   revoked token (force_logout), both routes -> 401 "Session revoked — please
#     log in again" without WWW-Authenticate.
#   valid token for a username that no longer exists, both routes -> 404
#     "User not found" without WWW-Authenticate.
#   Origin https://staterbill.com -> access-control-allow-origin is set, but
#     access-control-expose-headers is only "X-Total-Count" and the 401 has no
#     WWW-Authenticate.
"""
tests/test_session_rejection_marker.py
======================================
Bug condition exploration for C4.6 (bugfix 1.28 and 1.30, design Property 1
and Property 6): when the billing API rejects the session token itself, the
response carries the session-rejection marker

    WWW-Authenticate: Bearer error="invalid_token"

so clients sign out on that marker only, not on every 401 or 404 (2.28, 2.30).
The status codes and detail texts stay as they are (3.1). Browsers can read the
header only when CORS exposes it.

Cases: an expired and a revoked (token version bumped) token on GET /profile
and GET /settings; the "User not found" 404s of both routes, reached with a
valid token whose username no longer exists; and a 401 for an allowed origin.
"""
import os
import sys
import uuid
from datetime import timedelta

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_bizassist.db")
os.environ.setdefault("GROQ_API_KEY", "mock_groq_api_key")
os.environ.setdefault("CLOUD_API_URL", "http://127.0.0.1:9")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest
from fastapi.testclient import TestClient

from main_groq import app
import services.auth as auth
from tests.signup_fixture import signup_payload

client = TestClient(app)
PASSWORD = "Password123!"
MARKER = 'Bearer error="invalid_token"'
ALLOWED_ORIGIN = "https://staterbill.com"


@pytest.fixture(autouse=True)
def _isolated_auth_state():
    from services.rate_limiter import _ip_window, _upload_window
    _ip_window.clear()
    _upload_window.clear()
    yield
    auth.clear_token_version_cache()


def _new_owner() -> dict:
    username = f"own_srm_{uuid.uuid4().hex[:10]}"
    r = client.post("/signup", json=signup_payload({
        "username": username, "password": PASSWORD, "business_name": "Session Marker Store",
    }))
    assert r.status_code == 200, r.text
    return r.json()


def _claims(owner: dict) -> dict:
    return {k: owner[k] for k in ("id", "user_id", "username", "public_id", "business_name", "role")}


def _expired_token(owner: dict) -> str:
    return auth.create_access_token(_claims(owner), expires_delta=timedelta(seconds=-30))


def _revoked_token(owner: dict) -> str:
    from database.db import SessionLocal
    from services.admin_service import force_logout
    db = SessionLocal()
    try:
        force_logout(owner["id"], db)
    finally:
        db.close()
    return owner["token"]


def _token_of_missing_username(owner: dict) -> str:
    # Live subject and current token version, but no account with this username,
    # so the route itself answers "User not found".
    return auth.create_access_token({**_claims(owner), "username": f"gone_{uuid.uuid4().hex[:8]}"})


def _observed(resp) -> dict:
    return {
        "status": resp.status_code,
        "detail": resp.json().get("detail"),
        "www_authenticate": resp.headers.get("www-authenticate"),
    }


@pytest.mark.parametrize("route", ["/profile", "/settings"])
@pytest.mark.parametrize("make_token, detail", [
    pytest.param(_expired_token, "Signature has expired", id="expired"),
    pytest.param(_revoked_token, "Session revoked — please log in again", id="revoked"),
])
def test_rejected_session_tokens_carry_the_marker(route, make_token, detail):
    """**Validates: Requirements 1.28 (expected 2.28, 3.1)**"""
    token = make_token(_new_owner())
    r = client.get(route, headers={"Authorization": f"Bearer {token}"})
    assert _observed(r) == {"status": 401, "detail": detail, "www_authenticate": MARKER}


@pytest.mark.parametrize("route", ["/profile", "/settings"])
def test_user_not_found_404_carries_the_marker(route):
    """**Validates: Requirements 1.30 (expected 2.30)**"""
    token = _token_of_missing_username(_new_owner())
    r = client.get(route, headers={"Authorization": f"Bearer {token}"})
    assert _observed(r) == {"status": 404, "detail": "User not found", "www_authenticate": MARKER}


def test_cors_exposes_the_marker_to_an_allowed_origin():
    """**Validates: Requirements 1.28, 1.30 (expected 2.28, 2.30)**"""
    token = _expired_token(_new_owner())
    r = client.get("/profile", headers={"Authorization": f"Bearer {token}", "Origin": ALLOWED_ORIGIN})
    exposed = [h.strip().lower() for h in r.headers.get("access-control-expose-headers", "").split(",")]
    assert {
        "status": r.status_code,
        "allow_origin": r.headers.get("access-control-allow-origin"),
        "exposes_www_authenticate": "www-authenticate" in exposed,
        "www_authenticate": r.headers.get("www-authenticate"),
    } == {
        "status": 401,
        "allow_origin": ALLOWED_ORIGIN,
        "exposes_www_authenticate": True,
        "www_authenticate": MARKER,
    }, f"access-control-expose-headers: {r.headers.get('access-control-expose-headers')!r}"
