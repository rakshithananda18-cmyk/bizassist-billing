"""
tests/test_connection_approval.py
=================================
Regression tests for the B2B connection CONSENT model (review findings F-1/F-2).

The property under test is blunt: **knowing a business's BizID must not grant
any access to that business.** BizID is printed on invoices and shared publicly,
so if a bare `POST /connections/connect` produced a live link, anyone could
enumerate a competitor's full catalogue, tiered pricing and exact stock counts.

Covered here:
  1. a BizID request lands as `pending`, not `accepted`
  2. while pending, the catalogue and order endpoints stay closed (403)
  3. the requester cannot approve their own request
  4. only the counterparty can approve; approving opens the catalogue
  5. rejection and withdrawal both leave the pipe shut
  6. revocation is STICKY — the revoked party cannot re-open it unilaterally
  7. the invite-code path still accepts immediately (handing over a single-use
     code IS the consent)
  8. mutual requests auto-resolve (both sides explicitly opted in)
"""
import os
import sys

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_bizassist.db")

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

import pytest
from fastapi.testclient import TestClient
from main_groq import app
from database.db import SessionLocal
from database.models import User
from core.models import B2BConnection

client = TestClient(app)

SELLER = ("approval_seller", "ApprovalSeller123", "Approval Seller Co")
BUYER = ("approval_buyer", "ApprovalBuyer123", "Approval Buyer Co")
THIRD = ("approval_third", "ApprovalThird123", "Approval Third Co")


# ── Helpers ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def clear_rate_limit_windows():
    from services.rate_limiter import _ip_window, _upload_window
    _ip_window.clear()
    _upload_window.clear()


def _signup(username, password, business_name):
    client.post("/signup", json={
        "username": username, "password": password, "business_name": business_name,
    })


def _headers(username, password):
    resp = client.post("/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['token']}"}


def _bizid(headers):
    return client.get("/bizid", headers=headers).json()["public_id"]


def _wipe_link(a_user, b_user):
    """Remove any connection row between two usernames so each test starts clean."""
    db = SessionLocal()
    try:
        ids = [u.id for u in db.query(User).filter(User.username.in_([a_user, b_user])).all()]
        if len(ids) == 2:
            db.query(B2BConnection).filter(
                B2BConnection.seller_business_id.in_(ids),
                B2BConnection.buyer_business_id.in_(ids),
            ).delete(synchronize_session=False)
            db.commit()
    finally:
        db.close()


@pytest.fixture(scope="module", autouse=True)
def accounts():
    for creds in (SELLER, BUYER, THIRD):
        _signup(*creds)
    yield


@pytest.fixture
def ctx():
    """Fresh, unconnected seller/buyer pair for every test."""
    _wipe_link(SELLER[0], BUYER[0])
    seller_h = _headers(SELLER[0], SELLER[1])
    buyer_h = _headers(BUYER[0], BUYER[1])
    return {
        "seller_h": seller_h,
        "buyer_h": buyer_h,
        "seller_bizid": _bizid(seller_h),
        "buyer_bizid": _bizid(buyer_h),
    }


def _request_as_buyer(ctx, message=None):
    return client.post("/connections/connect", json={
        "bizid": ctx["seller_bizid"], "connect_as": "buyer", "message": message,
    }, headers=ctx["buyer_h"])


# ── 1. A BizID request does NOT create a live link ──────────────────────────

def test_bizid_request_lands_as_pending_not_accepted(ctx):
    resp = _request_as_buyer(ctx, message="We restock monthly")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["status"] == "pending", "F-1: a BizID request must never auto-accept"
    assert body["request_message"] == "We restock monthly"
    assert body["responded_at"] is None
    assert body["is_outgoing_request"] is True      # from the requester's view
    assert body["is_incoming_request"] is False


def test_pending_link_is_not_listed_as_a_real_connection(ctx):
    _request_as_buyer(ctx)

    buyer_view = client.get("/connections", headers=ctx["buyer_h"]).json()
    assert buyer_view["as_buyer"] == [], "a pending request is not a supplier yet"
    assert len(buyer_view["outgoing_requests"]) == 1
    assert buyer_view["counts"]["outgoing"] == 1

    seller_view = client.get("/connections", headers=ctx["seller_h"]).json()
    assert seller_view["as_seller"] == [], "a pending request is not a customer yet"
    assert len(seller_view["incoming_requests"]) == 1
    assert seller_view["incoming_requests"][0]["is_incoming_request"] is True


# ── 2. Nothing leaks while pending ───────────────────────────────────────────

def test_catalogue_stays_closed_while_pending(ctx):
    _request_as_buyer(ctx)
    resp = client.get(f"/connections/catalog/{ctx['seller_bizid']}", headers=ctx["buyer_h"])
    assert resp.status_code == 403, "F-1: catalogue/stock must not be readable before approval"


def test_orders_stay_closed_while_pending(ctx):
    _request_as_buyer(ctx)
    resp = client.post("/connections/orders", json={
        "seller_bizid": ctx["seller_bizid"],
        "items": [{"product_id": 1, "quantity": 1}],
    }, headers=ctx["buyer_h"])
    assert resp.status_code in (400, 403), "no order may be placed on a pending link"


# ── 3-4. Only the counterparty may approve ──────────────────────────────────

def test_requester_cannot_approve_their_own_request(ctx):
    conn_id = _request_as_buyer(ctx).json()["id"]
    resp = client.post(f"/connections/connections/{conn_id}/approve", headers=ctx["buyer_h"])
    assert resp.status_code == 403
    assert "own connection request" in resp.json()["detail"]


def test_unrelated_business_cannot_approve(ctx):
    conn_id = _request_as_buyer(ctx).json()["id"]
    third_h = _headers(THIRD[0], THIRD[1])
    resp = client.post(f"/connections/connections/{conn_id}/approve", headers=third_h)
    # 403 = explicitly denied (unrelated business recognised, access blocked).
    # 404 = opaque not-found (connection not visible to third party — equally
    #       correct since no connection data is leaked).
    # 400 = ValueError from service layer (e.g. connection not found by ID).
    # Any 4xx satisfies the security property: the unrelated business cannot approve.
    assert 400 <= resp.status_code < 500, (
        f"Expected denial (4xx) for unrelated business, got {resp.status_code}: {resp.text}"
    )


def test_counterparty_approval_opens_the_link(ctx):
    conn_id = _request_as_buyer(ctx).json()["id"]

    resp = client.post(f"/connections/connections/{conn_id}/approve", headers=ctx["seller_h"])
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "accepted"
    assert body["responded_at"] is not None

    # The link now shows up as a real relationship on both sides…
    buyer_view = client.get("/connections", headers=ctx["buyer_h"]).json()
    assert len(buyer_view["as_buyer"]) == 1
    assert buyer_view["outgoing_requests"] == []

    # …and the catalogue is readable.
    cat = client.get(f"/connections/catalog/{ctx['seller_bizid']}", headers=ctx["buyer_h"])
    assert cat.status_code == 200
    assert "items" in cat.json()


def test_approve_is_idempotent(ctx):
    conn_id = _request_as_buyer(ctx).json()["id"]
    client.post(f"/connections/connections/{conn_id}/approve", headers=ctx["seller_h"])
    again = client.post(f"/connections/connections/{conn_id}/approve", headers=ctx["seller_h"])
    assert again.status_code == 200
    assert again.json()["status"] == "accepted"


# ── 5. Rejection / withdrawal ────────────────────────────────────────────────

def test_rejection_keeps_the_pipe_shut(ctx):
    conn_id = _request_as_buyer(ctx).json()["id"]

    resp = client.post(f"/connections/connections/{conn_id}/reject", headers=ctx["seller_h"])
    assert resp.status_code == 200
    assert resp.json()["status"] == "rejected"

    cat = client.get(f"/connections/catalog/{ctx['seller_bizid']}", headers=ctx["buyer_h"])
    assert cat.status_code == 403


def test_rejected_request_can_be_raised_again_but_still_needs_approval(ctx):
    conn_id = _request_as_buyer(ctx).json()["id"]
    client.post(f"/connections/connections/{conn_id}/reject", headers=ctx["seller_h"])

    again = _request_as_buyer(ctx)
    assert again.status_code == 200
    assert again.json()["status"] == "pending", "re-requesting must not bypass approval"


def test_requester_can_withdraw_and_the_inbox_clears(ctx):
    conn_id = _request_as_buyer(ctx).json()["id"]

    resp = client.post(f"/connections/connections/{conn_id}/cancel", headers=ctx["buyer_h"])
    assert resp.status_code == 200

    seller_view = client.get("/connections", headers=ctx["seller_h"]).json()
    assert seller_view["incoming_requests"] == []


def test_counterparty_cannot_withdraw_someone_elses_request(ctx):
    conn_id = _request_as_buyer(ctx).json()["id"]
    resp = client.post(f"/connections/connections/{conn_id}/cancel", headers=ctx["seller_h"])
    assert resp.status_code == 403


# ── 6. Revocation is sticky ──────────────────────────────────────────────────

def test_revoked_party_cannot_restore_its_own_access(ctx):
    """F-2: re-POSTing connect used to flip a revoked row straight back to
    accepted, letting the revoked business restore access to itself."""
    conn_id = _request_as_buyer(ctx).json()["id"]
    client.post(f"/connections/connections/{conn_id}/approve", headers=ctx["seller_h"])

    revoke = client.post(f"/connections/connections/{conn_id}/revoke", headers=ctx["seller_h"])
    assert revoke.status_code == 200
    assert revoke.json()["status"] == "revoked"

    # The buyer tries to reconnect on their own.
    retry = _request_as_buyer(ctx)
    assert retry.status_code == 200
    assert retry.json()["status"] == "pending", "F-2: revocation must not be self-reversible"

    # And they still cannot read the catalogue.
    cat = client.get(f"/connections/catalog/{ctx['seller_bizid']}", headers=ctx["buyer_h"])
    assert cat.status_code == 403

    # Only the seller can let them back in.
    reopen = client.post(f"/connections/connections/{conn_id}/approve", headers=ctx["seller_h"])
    assert reopen.status_code == 200
    assert reopen.json()["status"] == "accepted"


# ── 7. The invite-code path is still instant ─────────────────────────────────

def test_invite_code_redemption_still_accepts_immediately(ctx):
    """Handing someone a single-use, expiring code IS the consent, so this path
    is deliberately exempt from the approval requirement."""
    code = client.post("/connections/code", headers=ctx["seller_h"]).json()["code"]

    resp = client.post("/connections/redeem", json={"code": code}, headers=ctx["buyer_h"])
    assert resp.status_code == 200
    assert resp.json()["status"] == "accepted"

    cat = client.get(f"/connections/catalog/{ctx['seller_bizid']}", headers=ctx["buyer_h"])
    assert cat.status_code == 200


# ── 8. Mutual intent resolves itself ─────────────────────────────────────────

def test_mutual_requests_auto_accept(ctx):
    """If B asks A, and then A asks B for the same relationship, both sides have
    explicitly opted in — no reason to make either of them click Approve."""
    first = _request_as_buyer(ctx)
    assert first.json()["status"] == "pending"

    mirror = client.post("/connections/connect", json={
        "bizid": ctx["buyer_bizid"], "connect_as": "seller",
    }, headers=ctx["seller_h"])
    assert mirror.status_code == 200
    assert mirror.json()["status"] == "accepted"


# ── Serializer contract the frontend depends on ─────────────────────────────

def test_connection_payload_exposes_viewer_relative_fields(ctx):
    _request_as_buyer(ctx)
    seller_view = client.get("/connections", headers=ctx["seller_h"]).json()
    req = seller_view["incoming_requests"][0]

    for field in ("my_role", "is_incoming_request", "is_outgoing_request",
                  "counterparty_name", "counterparty_bizid", "requested_by_business_id"):
        assert field in req, f"frontend relies on '{field}' to route Approve/Decline"

    assert req["my_role"] == "seller"
    assert req["counterparty_name"] == BUYER[2]


def test_list_connections_is_paginated(ctx):
    _request_as_buyer(ctx)
    resp = client.get("/connections?limit=1&offset=0", headers=ctx["buyer_h"])
    assert resp.status_code == 200
    body = resp.json()
    assert body["limit"] == 1 and body["offset"] == 0
    assert "total" in body


def test_invalid_status_filter_is_rejected(ctx):
    resp = client.get("/connections?status=bogus", headers=ctx["buyer_h"])
    assert resp.status_code == 400


# ── R3: an UNKNOWN requester must fail closed ───────────────────────────────
#
# `requested_by_business_id` is nullable — it was added by ALTER TABLE to a
# populated table, and rows also arrive from data-transfer imports and the
# cloud→local mirror without it. Every consent check was written as `==` / `!=`,
# and NULL loses both comparisons, so a NULL requester read as "somebody other
# than you" everywhere. That reopened F-1 in full: sending the same request
# twice made the second call take the mutual-intent branch and self-approve.
#
# These tests pin the fix: unknown requester ⇒ nobody may approve, nothing
# auto-accepts, and re-requesting CLAIMS the row instead of accepting it.

def _unclaim(ctx):
    """Blank the requester on the pending row, reproducing a legacy/imported row."""
    db = SessionLocal()
    try:
        ids = [u.id for u in db.query(User).filter(
            User.username.in_([SELLER[0], BUYER[0]])).all()]
        conn = db.query(B2BConnection).filter(
            B2BConnection.seller_business_id.in_(ids),
            B2BConnection.buyer_business_id.in_(ids),
        ).first()
        assert conn is not None
        conn.requested_by_business_id = None
        db.commit()
        return conn.id
    finally:
        db.close()


def _status_of(cid):
    db = SessionLocal()
    try:
        return db.query(B2BConnection).filter(B2BConnection.id == cid).first().status
    finally:
        db.close()


def test_resending_an_unclaimed_request_does_not_self_accept(ctx):
    """THE regression. Under the bug this second call returned 'accepted'."""
    _request_as_buyer(ctx)
    cid = _unclaim(ctx)

    resp = _request_as_buyer(ctx)
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "pending", (
        "F-1 reopened: a NULL requester let the sender approve their own request"
    )
    assert _status_of(cid) == "pending"


def test_resending_an_unclaimed_request_claims_it_for_the_sender(ctx):
    """Claiming is the safe repair: it names an approver, and it isn't the sender."""
    _request_as_buyer(ctx)
    cid = _unclaim(ctx)
    _request_as_buyer(ctx)

    buyer_view = client.get("/connections", headers=ctx["buyer_h"]).json()
    assert len(buyer_view["outgoing_requests"]) == 1
    assert buyer_view["unclaimed_requests"] == []

    seller_view = client.get("/connections", headers=ctx["seller_h"]).json()
    assert len(seller_view["incoming_requests"]) == 1, "the decision moved to the seller"

    # And the seller — the counterparty — can still complete it normally.
    assert client.post(f"/connections/{cid}/approve", headers=ctx["seller_h"]).status_code == 200
    assert _status_of(cid) == "accepted"


def test_nobody_can_approve_a_request_with_no_recorded_sender(ctx):
    _request_as_buyer(ctx)
    cid = _unclaim(ctx)

    for who in ("buyer_h", "seller_h"):
        resp = client.post(f"/connections/{cid}/approve", headers=ctx[who])
        assert resp.status_code == 403, f"{who} approved an unattributable request"
    assert _status_of(cid) == "pending"


def test_unclaimed_request_is_neither_incoming_nor_outgoing_but_still_visible(ctx):
    """It must not offer an Approve button — and must not vanish from the UI either."""
    _request_as_buyer(ctx)
    _unclaim(ctx)

    for who in ("buyer_h", "seller_h"):
        view = client.get("/connections", headers=ctx[who]).json()
        assert view["incoming_requests"] == []
        assert view["outgoing_requests"] == []
        assert len(view["unclaimed_requests"]) == 1, "row would be invisible in the UI"
        assert view["unclaimed_requests"][0]["requester_unknown"] is True
        assert view["counts"]["unclaimed"] == 1


def test_unclaimed_request_leaks_nothing(ctx):
    """The whole point: no consent recorded ⇒ no catalogue."""
    _request_as_buyer(ctx)
    _unclaim(ctx)
    resp = client.get(f"/connections/catalog/{ctx['seller_bizid']}", headers=ctx["buyer_h"])
    assert resp.status_code == 403


def test_unclaimed_request_cannot_be_cancelled_by_a_stranger(ctx):
    """Cancel DELETES the row, so it must fail closed on an unknown requester."""
    _request_as_buyer(ctx)
    cid = _unclaim(ctx)
    for who in ("buyer_h", "seller_h"):
        assert client.post(f"/connections/{cid}/cancel", headers=ctx[who]).status_code == 403
    assert _status_of(cid) == "pending"


def test_unclaimed_request_can_still_be_rejected(ctx):
    """Reject only ever DENIES, so failing open in the deny direction is fine —
    and it gives the counterparty a way to clear an unattributable row."""
    _request_as_buyer(ctx)
    cid = _unclaim(ctx)
    assert client.post(f"/connections/{cid}/reject", headers=ctx["seller_h"]).status_code == 200
    assert _status_of(cid) == "rejected"


def test_mutual_auto_accept_still_requires_a_known_requester(ctx):
    """The legitimate mutual-intent path must keep working — the fix narrows it,
    it does not remove it."""
    _request_as_buyer(ctx)
    resp = client.post("/connections/connect", json={
        "bizid": ctx["buyer_bizid"], "connect_as": "seller",
    }, headers=ctx["seller_h"])
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "accepted", "both parties explicitly opted in"
