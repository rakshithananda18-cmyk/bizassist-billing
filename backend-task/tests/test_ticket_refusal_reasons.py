"""Bug condition exploration, task 1.5 (Property 1 and Property 4; clauses 1.5 and 1.6).

Expected behaviour (2.5, 2.6, design.md C3 item 3): each hand-off ticket
refusal returns its own `detail` and logs `reason=<reason>`, and a 90 s
`field_team` ticket redeemed 100 s after minting (inside the 15 s leeway) signs
the owner in. Tickets come from billing's real `create_sse_ticket`, as in
test_billing_contract.py. The unfixed function has no `aud` argument, so `iat`
and `aud` go into the payload dict, which the fixed function keeps. One frozen
`time.time()` drives billing's minting and Field Team's redemption.

The refusal cases use 30 s tickets, which the unfixed lifetime cap (60 s)
accepts, so each counterexample shows the message defect on its own. The 90 s
case shows the lifetime defect.
"""
# Observed on the unfixed code (task 1.5, every case fails as expected):
#   bad_signature  (30 s ticket signed with another key, redeemed at 1 s)
#                  -> 401 "Sign-in link expired — open Field Team from BizAssist Billing again", nothing logged
#   expired        (30 s ticket redeemed at 60 s, exp + 30)
#                  -> 401 with the same detail, nothing logged
#   already_used   (30 s ticket: first redemption 200, second at 2 s)
#                  -> 401 with the same detail, nothing logged
#   audience       (30 s ticket with aud=ai_dashboard, redeemed at 1 s)
#                  -> 200: the owner is signed in, because `aud` is never checked
#   90 s field_team ticket redeemed at 100 s (exp + 10, inside the 15 s leeway)
#                  -> 401 "Sign-in link expired — ...": refused at `now > exp`, no leeway
# Confirms root cause 9 (one `refused` exception for every reason, no refusal
# log) and root cause 4 (`_TICKET_MAX_LIFETIME_S = 60`, no grace after exp).

import logging
import os
import sys
import time
from pathlib import Path

import pytest

from app import config, security

_REPO = Path(__file__).resolve().parents[2]
BILLING_DIR = os.environ.get("BILLING_BACKEND_DIR") or str(_REPO / "backend")
pytestmark = pytest.mark.skipif(
    not os.path.isfile(os.path.join(BILLING_DIR, "services", "auth.py")),
    reason="billing's backend/services/auth.py is needed to mint real hand-off tickets",
)

# A different key on the billing side: Billing and Field Team deployed with different JWT_SECRET values.
OTHER_SECRET = "another-billing-secret-0123456789abcdef"

# design.md C3 item 3: the `detail` shown to the owner for each refusal reason.
DETAIL = {
    "bad_signature": ("Field Team could not verify this sign-in link. Field Team and Billing are not set up "
                      "with the same sign-in key; ask your administrator to check the deployment."),
    "expired": "Sign-in link expired. Open Field Team from BizAssist Billing again.",
    "already_used": "This sign-in link was already used. Open Field Team from BizAssist Billing again.",
    "audience": "This sign-in link is not valid for Field Team. Open Field Team from BizAssist Billing again.",
}


def _billing_auth():
    # Appended, not prepended, as in test_billing_contract.py: billing's backend
    # has its own top-level app.py, and Field Team's `app` package keeps that name.
    if BILLING_DIR not in sys.path:
        sys.path.append(BILLING_DIR)
    return __import__("services.auth", fromlist=["_"])


class _Clock:
    """`time.time()` frozen at a chosen instant for every caller in the process."""

    def __init__(self, monkeypatch):
        self.now = float(int(time.time()))
        monkeypatch.setattr(time, "time", lambda: self.now)

    def advance(self, seconds):
        self.now += seconds


@pytest.fixture
def clock(monkeypatch):
    return _Clock(monkeypatch)


@pytest.fixture(autouse=True)
def _fresh_spent_set():
    spent = getattr(security, "_USED_TICKETS", None)
    if hasattr(spent, "clear"):
        spent.clear()
    yield
    if hasattr(spent, "clear"):
        spent.clear()


def _mint(biz, clock, *, lifetime, aud="field_team"):
    """A ticket minted now (frozen) by billing's create_sse_ticket, with `iat` and `aud` signed in."""
    return _billing_auth().create_sse_ticket({
        "id": biz.business_id, "user_id": biz.business_id, "username": biz.username,
        "public_id": biz.public_id, "role": "enterprise", "tv": 0,
        "iat": int(clock.now), "aud": aud,
    }, expires_in_seconds=lifetime)


def _exchange(client, ticket):
    return client.post("/api/auth/exchange", json={"ticket": ticket})


def _bad_signature(client, biz, clock, monkeypatch):
    with monkeypatch.context() as m:
        m.setattr(_billing_auth(), "JWT_SECRET", OTHER_SECRET)
        ticket = _mint(biz, clock, lifetime=30)
    clock.advance(1)
    return ticket, _exchange(client, ticket)


def _expired(client, biz, clock, monkeypatch):
    ticket = _mint(biz, clock, lifetime=30)
    clock.advance(60)  # 30 s past exp, well beyond the 15 s leeway
    return ticket, _exchange(client, ticket)


def _already_used(client, biz, clock, monkeypatch):
    ticket = _mint(biz, clock, lifetime=30)
    clock.advance(1)
    first = _exchange(client, ticket)
    assert first.status_code == 200, f"the first redemption must sign in: {first.status_code} {first.text}"
    clock.advance(1)
    return ticket, _exchange(client, ticket)


def _wrong_audience(client, biz, clock, monkeypatch):
    ticket = _mint(biz, clock, lifetime=30, aud="ai_dashboard")  # an AI dashboard ticket replayed here
    clock.advance(1)
    return ticket, _exchange(client, ticket)


SCENARIOS = {
    "bad_signature": _bad_signature,
    "expired": _expired,
    "already_used": _already_used,
    "audience": _wrong_audience,
}


@pytest.mark.parametrize("reason", list(SCENARIOS))
def test_each_refusal_returns_its_own_detail_and_logs_the_reason(client, biz, clock, monkeypatch, caplog, reason):
    """**Validates: Requirements 1.6, 2.6** (Property 4: each refusal has its own message and logged reason)."""
    caplog.set_level(logging.INFO)
    caplog.set_level(logging.INFO, logger="bizassist")
    ticket, r = SCENARIOS[reason](client, biz, clock, monkeypatch)

    messages = [rec.getMessage() for rec in caplog.records]
    observed = {"status": r.status_code, "detail": r.json().get("detail"),
                "reason_logged": any(f"reason={reason}" in m for m in messages)}
    assert observed == {"status": 401, "detail": DETAIL[reason], "reason_logged": True}, (
        f"{reason}: observed {observed}; log lines {messages}")
    _, payload, signature = ticket.split(".", 2)
    leaked = [name for name, value in (("JWT_SECRET", config.JWT_SECRET), ("ticket payload", payload),
                                       ("ticket signature", signature)) if value in caplog.text]
    assert not leaked, f"{reason}: the refusal log reveals {leaked}"


def test_90s_ticket_redeemed_at_100s_signs_the_owner_in(client, biz, clock):
    """**Validates: Requirements 1.5, 2.5** (Property 4: `r <= exp + 15 s` and `exp - iat <= 120 s` is accepted)."""
    ticket = _mint(biz, clock, lifetime=90)  # what Billing mints for Field Team after the fix
    clock.advance(100)  # a cold start of up to 60 s plus the page load
    r = _exchange(client, ticket)

    assert r.status_code == 200, f"a 90 s ticket at 100 s was refused: {r.status_code} {r.text}"
    body = r.json()
    assert body["kind"] == "owner" and body["public_id"] == biz.public_id


def test_restarting_the_service_cannot_reuse_a_spent_ticket(client, biz, clock):
    import hashlib
    from app.db import SessionLocal
    from app.models import FieldHandoffTicketUse

    ticket = _mint(biz, clock, lifetime=90)
    assert _exchange(client, ticket).status_code == 200
    security._USED_TICKETS.clear()
    clock.advance(1)
    response = _exchange(client, ticket)
    assert response.status_code == 401
    assert response.json()["detail"] == DETAIL["already_used"]
    with SessionLocal() as db:
        stored = db.query(FieldHandoffTicketUse).filter(
            FieldHandoffTicketUse.business_id == biz.business_id,
            FieldHandoffTicketUse.digest == hashlib.sha256(ticket.encode()).hexdigest(),
        ).one()
        assert stored.digest != ticket
        assert stored.expires_at == int(ticket.split(".", 1)[0]) + 15
