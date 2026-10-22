"""The contract with BizAssist Billing, checked against billing's REAL code.

Field Team reads billing's `users` / `customers` rows and accepts billing's
hand-off ticket. Elsewhere in this suite those sides are mirrored (a copy of
the columns, a copy of the ticket format); here they are imported from
billing itself, so a billing change that would break Field Team fails CI.

Runs when BILLING_BACKEND_DIR points at bizassist-billing/backend (the
Field Team workflow's contract job sets it); skipped otherwise.
"""
import os
import sys

import pytest

from tests.conftest import auth

BILLING_DIR = os.environ.get("BILLING_BACKEND_DIR")
pytestmark = pytest.mark.skipif(not BILLING_DIR, reason="set BILLING_BACKEND_DIR to check the billing contract")


def _billing(module):
    # Appended, not prepended: billing's backend has its own top-level `app.py`,
    # and Field Team's `app` package must keep winning that name.
    if BILLING_DIR not in sys.path:
        sys.path.append(BILLING_DIR)
    return __import__(module, fromlist=["_"])


def test_columns_field_team_reads_exist_in_billing_models():
    billing = _billing("database.models")
    from app.billing_models import BillingCustomer, BillingUser

    for mirror, real in ((BillingUser, billing.User), (BillingCustomer, billing.Customer)):
        assert mirror.__tablename__ == real.__tablename__
        real_cols = {c.name: c for c in real.__table__.columns}
        missing = [c.name for c in mirror.__table__.columns if c.name not in real_cols]
        assert not missing, f"billing.{real.__tablename__} no longer has {missing}"
        for col in mirror.__table__.columns:
            want = col.type.python_type
            got = real_cols[col.name].type.python_type
            assert got is want, f"{real.__tablename__}.{col.name}: billing {got.__name__}, Field Team {want.__name__}"


def test_ticket_minted_by_billing_signs_the_owner_in(client, biz):
    billing_auth = _billing("services.auth")
    ticket = billing_auth.create_sse_ticket({
        "id": biz.business_id, "user_id": biz.business_id, "username": biz.username,
        "public_id": biz.public_id, "role": "enterprise", "tv": 0,
    }, expires_in_seconds=30)

    r = client.post("/api/auth/exchange", json={"ticket": ticket})
    assert r.status_code == 200, r.text
    assert client.get("/api/staff", headers=auth(r.json()["token"])).status_code == 200
    assert client.post("/api/auth/exchange", json={"ticket": ticket}).status_code == 401
