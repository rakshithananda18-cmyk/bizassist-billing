"""
tests/test_shifts.py
====================
Shift & Cash-Drawer Management (plan Phase 3) — end-to-end lifecycle:

  1. Billing is LOCKED without an open shift (409 shift_required) — ALL roles.
  2. Open a shift with a counted float → /shifts/current returns it.
  3. Ring a cash sale → the shift's tally expects float + cash.
  4. UPI sales tally separately from cash.
  5. Close the shift with counted cash → expected snapshot + discrepancy.
  6. Owner report lists the reconciliation; a second open shift is rejected
     while one is OPEN, allowed after close.

Self-contained: own signups + product, order-independent.
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
from database.models import Product, User

client = TestClient(app)


@pytest.fixture(autouse=True)
def _clear_rate_limit():
    from services.rate_limiter import _ip_window, _upload_window
    _ip_window.clear()
    _upload_window.clear()


def _signup(name="Shift Biz"):
    uname = f"shift_{uuid.uuid4().hex[:8]}"
    r = client.post("/signup", json={"username": uname, "password": "TestPass123!",
                                     "business_name": name})
    assert r.status_code == 200, r.text
    b = r.json()
    bid = b["id"]
    db = SessionLocal()
    try:
        p = Product(business_id=bid, name="Shift Soap", unit="Nos",
                    selling_price=500, track_inventory=False,
                    cgst_rate=0, sgst_rate=0, igst_rate=0)
        db.add(p)
        db.commit()
        pid = p.id
    finally:
        db.close()
    return {"headers": {"Authorization": f"Bearer {b['token']}"}, "bid": bid, "pid": pid}


def _sale(headers, pid, price, mode="cash"):
    """POS 'Save Bill' — Paid & Print (full payable settled at the counter)."""
    return client.post("/invoices", headers=headers, json={
        "items": [{"product_id": pid, "product": "Shift Soap", "qty": 1, "price": price}],
        "gst_enabled": False,
        "mark_paid": True,
        "payment_mode": mode,
    })


# ── 1. Gatekeeper: billing locked without an open shift ──────────────────────

def test_billing_locked_without_open_shift():
    a = _signup()
    r = _sale(a["headers"], a["pid"], 500)
    assert r.status_code == 409, r.text
    assert "shift" in r.json()["detail"].lower()


# ── 2–5. The manual-verification scenario from the plan, automated ───────────
#    open with ₹1000 float → ₹500 cash sale → system expects ₹1500 at close.

def test_shift_lifecycle_cash_tally():
    a = _signup()

    # open with a ₹1000 float
    r = client.post("/shifts/open", headers=a["headers"], json={"opening_cash": 1000})
    assert r.status_code == 201, r.text
    shift = r.json()["shift"]
    assert shift["status"] == "OPEN" and shift["opening_cash"] == 1000.0

    # current returns it (with a live tally)
    r = client.get("/shifts/current", headers=a["headers"])
    assert r.status_code == 200
    cur = r.json()["shift"]
    assert cur["id"] == shift["id"]
    assert cur["tally"]["expected_cash"] == 1000.0

    # ₹500 cash sale under the shift
    r = _sale(a["headers"], a["pid"], 500, mode="cash")
    assert r.status_code == 201, r.text

    # tally: 1000 float + 500 cash = 1500 expected
    r = client.get(f"/shifts/{shift['id']}/tally", headers=a["headers"])
    assert r.status_code == 200
    t = r.json()["tally"]
    assert t["sales_cash"] == 500.0
    assert t["expected_cash"] == 1500.0
    assert t["expected_upi"] == 0.0

    # a ₹200 UPI sale tallies separately
    r = _sale(a["headers"], a["pid"], 200, mode="upi")
    assert r.status_code == 201, r.text
    t = client.get(f"/shifts/{shift['id']}/tally", headers=a["headers"]).json()["tally"]
    assert t["expected_cash"] == 1500.0
    assert t["expected_upi"] == 200.0

    # close counting ₹1450 cash (₹50 SHORT) and ₹200 UPI (exact)
    r = client.post("/shifts/close", headers=a["headers"],
                    json={"closing_cash_actual": 1450, "closing_upi_actual": 200})
    assert r.status_code == 200, r.text
    closed = r.json()["shift"]
    assert closed["status"] == "CLOSED"
    assert closed["closing_cash_expected"] == 1500.0
    assert closed["closing_cash_actual"] == 1450.0
    assert closed["cash_discrepancy"] == -50.0
    assert closed["closing_upi_expected"] == 200.0
    assert closed["upi_discrepancy"] == 0.0

    # after close: no current shift, and billing locks again
    assert client.get("/shifts/current", headers=a["headers"]).json()["shift"] is None
    assert _sale(a["headers"], a["pid"], 100).status_code == 409


# ── 6. One open shift per user; owner report shows the reconciliation ────────

def test_single_open_shift_and_owner_report():
    a = _signup()
    r = client.post("/shifts/open", headers=a["headers"], json={"opening_cash": 100})
    assert r.status_code == 201
    # a second open while one is OPEN → 409
    r = client.post("/shifts/open", headers=a["headers"], json={"opening_cash": 100})
    assert r.status_code == 409

    # close it exactly (no sales): expected == opening float
    r = client.post("/shifts/close", headers=a["headers"],
                    json={"closing_cash_actual": 100})
    assert r.status_code == 200
    assert r.json()["shift"]["cash_discrepancy"] == 0.0

    # a new shift may now be opened
    r = client.post("/shifts/open", headers=a["headers"], json={"opening_cash": 250})
    assert r.status_code == 201

    # owner-only listing + the flat report used by Reports → Shift Reconciliations
    r = client.get("/shifts", headers=a["headers"])
    assert r.status_code == 200
    assert r.json()["total"] == 2

    r = client.get("/reports/shift-reconciliations", headers=a["headers"])
    assert r.status_code == 200, r.text
    rows = r.json()
    assert len(rows) == 2
    closed_rows = [x for x in rows if x["status"] == "CLOSED"]
    assert closed_rows and closed_rows[0]["cash_short_over"] == 0.0


def test_negative_opening_cash_rejected():
    a = _signup()
    r = client.post("/shifts/open", headers=a["headers"], json={"opening_cash": -5})
    assert r.status_code == 422
    assert r.status_code == 422


# ── Phase 3b: float carry-forward + cash movements ────────────────────────────

def test_float_carries_forward_and_variance_is_recorded():
    a = _signup()

    # no history → no suggestion
    r = client.get("/shifts/suggested-float", headers=a["headers"])
    assert r.status_code == 200 and r.json()["suggested"] is None

    # shift 1: open 1000, count 1000, leave only 300 in drawer (700 → bank)
    client.post("/shifts/open", headers=a["headers"], json={"opening_cash": 1000})
    r = client.post("/shifts/close", headers=a["headers"],
                    json={"closing_cash_actual": 1000, "leave_in_drawer": 300,
                          "removal_destination": "bank_deposit"})
    assert r.status_code == 200, r.text
    s1 = r.json()["shift"]
    assert s1["closing_float"] == 300.0
    removals = [m for m in s1["movements"] if m["category"] == "closing_removal"]
    assert removals and removals[0]["amount"] == 700.0
    assert "Bank deposit" in removals[0]["note"]

    # next open is suggested at 300 (what was left in the drawer)
    r = client.get("/shifts/suggested-float", headers=a["headers"])
    assert r.json()["suggested"] == 300.0

    # shift 2: opened with 350 instead → opening variance +50 recorded (audit-only)
    r = client.post("/shifts/open", headers=a["headers"], json={"opening_cash": 350})
    assert r.status_code == 201
    s2 = r.json()["shift"]
    assert s2["opening_expected"] == 300.0
    variances = [m for m in s2["movements"] if m["category"] == "opening_variance"]
    assert variances and variances[0]["amount"] == 50.0
    # variance does NOT change the tally — entered opening cash is the truth
    t = client.get("/shifts/current", headers=a["headers"]).json()["shift"]["tally"]
    assert t["expected_cash"] == 350.0


def test_cash_movements_adjust_tally_and_expense_hits_books():
    from core.models import Expense as ExpenseModel
    a = _signup()
    client.post("/shifts/open", headers=a["headers"], json={"opening_cash": 1000})

    # ₹500 cash sale
    assert _sale(a["headers"], a["pid"], 500, mode="cash").status_code == 201

    # paid out ₹800 to the bank mid-shift
    r = client.post("/shifts/movements", headers=a["headers"], json={
        "movement_type": "paid_out", "category": "bank_deposit",
        "amount": 800, "note": "midday bank drop"})
    assert r.status_code == 201, r.text
    assert r.json()["tally"]["expected_cash"] == 700.0   # 1000 + 500 − 800

    # paid out ₹200 as a drawer expense → real Expense row in the books
    r = client.post("/shifts/movements", headers=a["headers"], json={
        "movement_type": "paid_out", "category": "expense",
        "amount": 200, "note": "tea & snacks", "expense_category": "Others"})
    assert r.status_code == 201, r.text
    mv = r.json()["movement"]
    assert mv["expense_id"] is not None
    assert r.json()["tally"]["expected_cash"] == 500.0   # 700 − 200

    db = SessionLocal()
    try:
        exp = db.query(ExpenseModel).filter(ExpenseModel.id == mv["expense_id"]).first()
        assert exp is not None and exp.amount == 200.0 and exp.payment_mode == "Cash"
        assert exp.business_id == a["bid"]
    finally:
        db.close()

    # paid in ₹100 change top-up
    r = client.post("/shifts/movements", headers=a["headers"], json={
        "movement_type": "paid_in", "category": "change_top_up", "amount": 100})
    assert r.status_code == 201
    assert r.json()["tally"]["expected_cash"] == 600.0   # 500 + 100

    # close counting exactly 600 → tallies; report shows the movements
    r = client.post("/shifts/close", headers=a["headers"],
                    json={"closing_cash_actual": 600})
    assert r.status_code == 200
    assert r.json()["shift"]["cash_discrepancy"] == 0.0
    assert r.json()["shift"]["closing_float"] == 600.0   # default: leave everything

    rows = client.get("/reports/shift-reconciliations", headers=a["headers"]).json()
    row = rows[0]
    assert row["paid_in"] == 100.0 and row["paid_out"] == 1000.0
    assert row["left_in_drawer"] == 600.0 and row["moved_out_at_close"] == 0.0


def test_movement_validation():
    a = _signup()
    # movements need an open shift
    r = client.post("/shifts/movements", headers=a["headers"], json={
        "movement_type": "paid_out", "category": "bank_deposit", "amount": 100})
    assert r.status_code == 409

    client.post("/shifts/open", headers=a["headers"], json={"opening_cash": 100})
    # bad category / amount / leave_in_drawer > counted
    r = client.post("/shifts/movements", headers=a["headers"], json={
        "movement_type": "paid_in", "category": "bank_deposit", "amount": 100})
    assert r.status_code == 422
    r = client.post("/shifts/movements", headers=a["headers"], json={
        "movement_type": "paid_out", "category": "bank_deposit", "amount": 0})
    assert r.status_code == 422
    r = client.post("/shifts/close", headers=a["headers"],
                    json={"closing_cash_actual": 100, "leave_in_drawer": 150})
    assert r.status_code == 422
