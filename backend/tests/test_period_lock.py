"""
tests/test_period_lock.py
=========================
Gate-1 coverage for R2 — period close/lock (books integrity).

Proves (negative-first):
  • the guard logic: assert_period_open raises in a closed period, passes in the
    open period, and passes again after unlock (unit-level, route-independent),
  • posting any money document into a locked period is REJECTED (422) and writes
    nothing — across sale / expense write paths,
  • idempotent re-post of a PRE-lock entry is NOT falsely blocked (the guard sits
    after the idempotency return),
  • unlock re-opens the period,
  • locking to an earlier date than the current lock is rejected (no silent
    re-open),
  • owner-only (cashier 403) and tenant isolation.

Self-contained: signs up its own owners + cashier and seeds its own data.
"""
import os
import sys
import uuid

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_bizassist.db")
os.environ.setdefault("GROQ_API_KEY", "mock_groq_api_key")

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, backend_path)

import pytest
from fastapi.testclient import TestClient
from main_groq import app
from database.db import SessionLocal
from database.models import Inventory, Invoice
from core.models import JournalEntry, PeriodLock
from core.accounting import posting, period_lock
from core.accounting.period_lock import PeriodLockedError

client = TestClient(app)

LOCK_THROUGH = "2026-06-30"
CLOSED_DAY = "2026-06-15"   # <= LOCK_THROUGH  → locked
OPEN_DAY = "2026-07-15"     # >  LOCK_THROUGH  → open


@pytest.fixture(autouse=True)
def _clear_rate_limit():
    from services.rate_limiter import _ip_window, _upload_window
    _ip_window.clear()
    _upload_window.clear()


def _owner(name):
    r = client.post("/signup", json={
        "username": f"o_{uuid.uuid4().hex[:8]}", "password": "Password123!", "business_name": name,
    })
    assert r.status_code == 200, r.text
    d = r.json()
    return {"headers": {"Authorization": f"Bearer {d['token']}"}, "bid": d["id"]}


def _cashier_of(owner):
    uname = f"c_{uuid.uuid4().hex[:8]}"
    r = client.post("/staff", headers=owner["headers"],
                    json={"username": uname, "password": "Password123!", "role": "cashier"})
    assert r.status_code == 201, r.text
    login = client.post("/login", json={"username": uname, "password": "Password123!"})
    return {"Authorization": f"Bearer {login.json()['token']}"}


def _product(owner):
    headers, bid = owner["headers"], owner["bid"]
    p = client.post("/products", headers=headers, json={
        "name": "PL Prod", "selling_price": 100.0, "cost_price": 60.0,
        "sku": f"PL-{uuid.uuid4().hex[:5]}", "track_inventory": True,
    })
    pid = p.json()["id"]
    db = SessionLocal()
    try:
        db.add(Inventory(business_id=bid, product_name="PL Prod", product_id=pid,
                         stock=500, cost_price=60.0, selling_price=100.0))
        db.commit()
    finally:
        db.close()
    return pid


def _sale(owner, pid, date, paid=40.0):
    return client.post("/sales", headers=owner["headers"], json={
        "lines": [{"product_id": pid, "product_name": "PL Prod", "quantity": 1.0,
                   "unit_price": 100.0, "cgst_rate": 9.0, "sgst_rate": 9.0, "igst_rate": 0.0}],
        "customer": "PL Cust", "invoice_no": f"INV-{uuid.uuid4().hex[:6]}",
        "invoice_date": date, "paid_amount": paid, "payment_mode": "UPI",
    })


def _lock(owner, through=LOCK_THROUGH):
    return client.post("/accounting/period-lock", headers=owner["headers"],
                       json={"through": through, "note": "month close"})


# ── Unit: the guard itself ────────────────────────────────────────────────────

def test_assert_period_open_guard_logic():
    bid = 9_000_000 + (uuid.uuid4().int % 900_000)
    db = SessionLocal()
    try:
        assert period_lock.effective_lock(db, bid) is None
        period_lock.assert_period_open(db, bid, CLOSED_DAY)  # open → no raise

        period_lock.lock_period(db, business_id=bid, through=LOCK_THROUGH)
        db.commit()
        assert period_lock.effective_lock(db, bid) == LOCK_THROUGH
        with pytest.raises(PeriodLockedError):
            period_lock.assert_period_open(db, bid, CLOSED_DAY)        # on/before → blocked
        with pytest.raises(PeriodLockedError):
            period_lock.assert_period_open(db, bid, LOCK_THROUGH)      # boundary inclusive
        period_lock.assert_period_open(db, bid, OPEN_DAY)              # after → ok

        period_lock.unlock_period(db, business_id=bid)
        db.commit()
        assert period_lock.effective_lock(db, bid) is None
        period_lock.assert_period_open(db, bid, CLOSED_DAY)            # re-opened → ok
    finally:
        db.query(PeriodLock).filter(PeriodLock.business_id == bid).delete()
        db.commit()
        db.close()


# ── API: locked-period writes are rejected and write nothing ──────────────────

def test_sale_in_locked_period_rejected_and_writes_nothing():
    owner = _owner("PL Sale")
    pid = _product(owner)
    assert _lock(owner).status_code == 200

    before = client.get("/reports/sales-register",
                        headers=owner["headers"], params={"limit": 2000}).json()
    r = _sale(owner, pid, CLOSED_DAY)
    assert r.status_code == 422, r.text
    assert "locked" in r.json().get("detail", "").lower()
    after = client.get("/reports/sales-register",
                       headers=owner["headers"], params={"limit": 2000}).json()
    assert len(after) == len(before), "a rejected sale must not create an invoice"


def test_expense_in_locked_period_rejected():
    owner = _owner("PL Exp")
    assert _lock(owner).status_code == 200
    r = client.post("/expenses", headers=owner["headers"], json={
        "expense_date": CLOSED_DAY, "category": "Rent", "expense_type": "Indirect",
        "amount": 500.0, "payment_mode": "Cash",
    })
    assert r.status_code == 422, r.text
    assert "locked" in r.json().get("detail", "").lower()


def test_sale_in_open_period_allowed_despite_lock():
    owner = _owner("PL Open")
    pid = _product(owner)
    assert _lock(owner).status_code == 200
    r = _sale(owner, pid, OPEN_DAY)   # after the lock boundary
    assert r.status_code == 200, r.text


def test_unlock_reopens_period():
    owner = _owner("PL Unlock")
    pid = _product(owner)
    assert _lock(owner).status_code == 200
    assert _sale(owner, pid, CLOSED_DAY).status_code == 422
    u = client.post("/accounting/period-unlock", headers=owner["headers"], json={"note": "reopen"})
    assert u.status_code == 200, u.text
    assert _sale(owner, pid, CLOSED_DAY).status_code == 200


# ── Idempotency: re-posting a PRE-lock entry is not falsely blocked ───────────

def test_idempotent_repost_of_prelock_entry_not_blocked():
    owner = _owner("PL Idem")
    pid = _product(owner)
    sale = _sale(owner, pid, CLOSED_DAY)      # posted BEFORE any lock
    assert sale.status_code == 200, sale.text
    inv_id = sale.json()["id"]
    assert _lock(owner).status_code == 200    # now close the period containing it

    db = SessionLocal()
    try:
        inv = db.query(Invoice).filter(Invoice.id == inv_id).first()
        posting.post_sale(db, inv)            # re-post: idempotency returns existing, guard not reached
        db.commit()
        n = db.query(JournalEntry).filter(
            JournalEntry.business_id == owner["bid"],
            JournalEntry.source_type == "sale",
            JournalEntry.source_id == inv_id,
        ).count()
        assert n == 1, "re-post must neither duplicate nor be blocked"
    finally:
        db.close()


# ── Lock management rules ─────────────────────────────────────────────────────

def test_locking_to_earlier_date_rejected():
    owner = _owner("PL Regress")
    assert _lock(owner, "2026-06-30").status_code == 200
    r = _lock(owner, "2026-05-31")            # earlier → would re-open May
    assert r.status_code == 409, r.text
    assert r.json().get("code") == "lock_regression"


def test_get_status_and_history():
    owner = _owner("PL Status")
    assert client.get("/accounting/period-lock", headers=owner["headers"]).json()["locked_through"] is None
    _lock(owner)
    body = client.get("/accounting/period-lock", headers=owner["headers"]).json()
    assert body["locked_through"] == LOCK_THROUGH
    assert len(body["history"]) >= 1


# ── RBAC + tenancy ────────────────────────────────────────────────────────────

def test_cashier_cannot_lock():
    owner = _owner("PL RBAC")
    cashier = _cashier_of(owner)
    assert client.post("/accounting/period-lock", headers=cashier,
                       json={"through": LOCK_THROUGH}).status_code == 403
    assert client.get("/accounting/period-lock", headers=cashier).status_code == 403


def test_lock_is_tenant_isolated():
    a, b = _owner("PL A"), _owner("PL B")
    pid_b = _product(b)
    assert _lock(a).status_code == 200                       # A closes its books
    assert client.get("/accounting/period-lock", headers=b["headers"]).json()["locked_through"] is None
    assert _sale(b, pid_b, CLOSED_DAY).status_code == 200    # B unaffected by A's lock
