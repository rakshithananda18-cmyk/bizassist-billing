# Observed counterexamples on the unfixed code (task 1.1):
#   POST /handoff-ticket {"purpose": "field_team"} -> 200, and the ticket has no
#     aud and no iat and lives 30 s (the body is ignored).
#   POST /redeem-ticket with an aud=field_team ticket -> 200 and a new session.
#   POST /redeem-ticket with a ticket minted before force_logout bumped the
#     token version -> 200 and a new session.
"""
tests/test_handoff_ticket_purpose.py
====================================
Bug condition exploration for C4.1 and C4.2 (bugfix 1.5 and 1.16, design
Property 1 and Property 4).

* POST /handoff-ticket with {"purpose": "field_team"} must mint a 90 s ticket
  that names its audience (aud) and carries iat, so the hand-off survives a
  Field Team cold start (2.5).
* POST /redeem-ticket serves the AI dashboard and the admin console. It must
  refuse a ticket meant for Field Team, and a ticket minted before the account's
  token version was bumped (a force logout), as the Field Team API does (2.16).

The unfixed create_sse_ticket has no aud argument, so the field_team ticket is
minted with "aud" inside the payload dict, which the fixed minting keeps as is.
"""
import base64
import json
import os
import sys
import time
import uuid

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


@pytest.fixture(autouse=True)
def _isolated_ticket_state():
    from services.rate_limiter import _ip_window, _upload_window
    _ip_window.clear()
    _upload_window.clear()
    auth._used_tickets.clear()
    yield
    auth._used_tickets.clear()


def _new_owner() -> dict:
    username = f"own_htp_{uuid.uuid4().hex[:10]}"
    r = client.post("/signup", json=signup_payload({
        "username": username, "password": PASSWORD, "business_name": "Hand-off Purpose Store",
    }))
    assert r.status_code == 200, r.text
    r = client.post("/login", json={"username": username, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return r.json()


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _decode_ticket(ticket: str) -> tuple:
    exp, b64, _sig = ticket.split(".", 2)
    return int(exp), json.loads(base64.urlsafe_b64decode(b64 + "=" * (-len(b64) % 4)))


def _force_logout(business_id: int) -> None:
    from database.db import SessionLocal
    from services.admin_service import force_logout
    db = SessionLocal()
    try:
        force_logout(business_id, db)
    finally:
        db.close()


def _body_keys(resp) -> object:
    try:
        body = resp.json()
    except ValueError:
        return resp.text[:200]
    return sorted(body) if isinstance(body, dict) else body


def test_field_team_purpose_mints_a_90_second_ticket_with_its_audience(monkeypatch):
    """**Validates: Requirements 1.5 (expected 2.5)**"""
    monkeypatch.delenv("HANDOFF_TTL_FIELD_TEAM", raising=False)
    owner = _new_owner()
    before = int(time.time())
    r = client.post("/handoff-ticket", json={"purpose": "field_team"}, headers=_auth(owner["token"]))
    after = int(time.time())
    assert r.status_code == 200, r.text
    exp, claims = _decode_ticket(r.json()["ticket"])
    aud, iat = claims.get("aud"), claims.get("iat")
    assert (
        aud == "field_team"
        and isinstance(iat, (int, float))
        and abs((exp - iat) - 90) <= 1
        and before + 89 <= exp <= after + 90
    ), (
        f"field_team ticket: aud={aud!r}, iat={iat!r}, lives about {exp - after} s; "
        "expected aud='field_team', an iat claim and a 90 s lifetime"
    )


def _ticket_for_field_team(owner: dict) -> str:
    claims = auth.decode_access_token(owner["token"])
    return auth.create_sse_ticket({**claims, "aud": "field_team"}, expires_in_seconds=90)


def _ticket_minted_before_force_logout(owner: dict) -> str:
    r = client.post("/handoff-ticket", headers=_auth(owner["token"]))
    assert r.status_code == 200, r.text
    _force_logout(owner["id"])
    return r.json()["ticket"]


@pytest.mark.parametrize("make_ticket", [
    pytest.param(_ticket_for_field_team, id="aud_field_team"),
    pytest.param(_ticket_minted_before_force_logout, id="minted_before_token_version_bump"),
])
def test_redeem_ticket_refuses_tickets_it_must_not_honour(make_ticket):
    """**Validates: Requirements 1.16 (expected 2.16)**"""
    owner = _new_owner()
    ticket = make_ticket(owner)
    r = client.post("/redeem-ticket", json={"ticket": ticket})
    assert r.status_code == 401, (
        f"/redeem-ticket returned {r.status_code} with {_body_keys(r)}; expected 401"
    )
