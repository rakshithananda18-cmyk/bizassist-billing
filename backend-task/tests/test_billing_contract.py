"""The contract with BizAssist Billing, checked against billing's REAL code.

Field Team reads billing's `users` / `customers` / `invoices` /
`invoice_line_items` rows, applies billing's Pro plan rule, and accepts billing's
hand-off ticket. Elsewhere in this suite those sides are mirrored (a copy of
the columns, a copy of the ticket format); here they are imported from
billing itself, so a billing change that would break Field Team fails CI.

Runs when BILLING_BACKEND_DIR points at bizassist-billing/backend (the
Field Team workflow's contract job sets it); skipped otherwise.
"""
import json
import os
import sys
from datetime import timedelta

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
    from app.billing_models import (
        BillingCustomer, BillingInvoice, BillingInvoiceLine, BillingInvoicePayment, BillingUser,
    )

    for mirror, real in ((BillingUser, billing.User), (BillingCustomer, billing.Customer),
                         (BillingInvoice, billing.Invoice), (BillingInvoiceLine, billing.InvoiceLineItem),
                         (BillingInvoicePayment, billing.InvoicePayment)):
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


def test_pro_plan_rule_matches_billings():
    """Field Team must call a business Pro exactly when billing does (plus its
    own grace period, which only applies after billing says "free")."""
    admin = _billing("services.admin_service")
    models = _billing("database.models")
    from app.billing_models import BillingUser
    from app.db import utc_now
    from app.plan import expiry_moment, plan_state

    today = utc_now().date()
    for raw in (None, "", "not a date", today.isoformat(), (today - timedelta(days=1)).isoformat(),
                "2026-10-23T20:00:00+05:30", "2026-10-23T10:00:00Z", "2026-10-23 10:00:00"):
        assert expiry_moment(raw) == admin.expiry_moment(raw), raw
    for sub in (None, {"plan": "free"}, {"plan": "pro"}, {"plan": "PRO"},
                {"plan": "pro", "expires_at": today.isoformat()},
                {"plan": "pro", "expires_at": (today - timedelta(days=2)).isoformat()}):
        settings = json.dumps({"subscription": sub} if sub else {})
        assert plan_state(BillingUser(settings=settings)).plan == admin.effective_plan(models.User(settings=settings)), sub


def test_billings_view_of_field_team_tables_matches_ours():
    """Billing reads ft_* (core/field_team.py) to confirm collections into
    payments. Every column it declares must exist here with the same type,
    and both sides must build the payment key the same way."""
    billing_ft = _billing("core.field_team")
    from app import models
    from app.collections import KEY_PREFIX

    ours = {m.__tablename__: m for m in (models.FieldTask, models.FieldShop, models.FieldStaff, models.FieldTaskInvoice)}
    for theirs in (billing_ft.FtTask, billing_ft.FtShop, billing_ft.FtStaff, billing_ft.FtTaskInvoice):
        real_cols = {c.name: c for c in ours[theirs.__tablename__].__table__.columns}
        for col in theirs.__table__.columns:
            assert col.name in real_cols, f"billing reads {theirs.__tablename__}.{col.name}, which Field Team does not have"
            assert real_cols[col.name].type.python_type is col.type.python_type, f"{theirs.__tablename__}.{col.name}"
    assert billing_ft.KEY_PREFIX == KEY_PREFIX
