"""
tests/test_phase1b.py
=====================
Comprehensive tests for all Phase 1B backend components:
  1. Products management (CRUD + barcodes + stock adjustment)
  2. Customers & Vendors management (CRUD + outstanding ledger statement)
  3. Payments API (idempotent record payment receipt)
  4. Credit Notes API (returns stock + creates CN invoice)
  5. Reports & Analytics (Daily summary + stock ledger query)
  6. Switch-in bulk imports (products + customers)
  7. Cashier RBAC (verifies cashier is blocked from reports, credit notes, imports)
"""
import os
import sys
import uuid
from datetime import datetime

os.environ["DATABASE_URL"] = "sqlite:///./test_bizassist.db"
os.environ["GROQ_API_KEY"] = "mock_groq_api_key"

# Clean up any leftover databases from previous runs before importing main_groq
for db_path in ["test_bizassist.db", "backend/test_bizassist.db"]:
    if os.path.exists(db_path):
        try:
            os.remove(db_path)
        except Exception:
            pass

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, backend_path)

import pytest
from fastapi.testclient import TestClient
from main_groq import app


@pytest.fixture(scope="session", autouse=True)
def cleanup_test_db():
    yield
    # Clean up test database files at session end
    for db_path in ["test_bizassist.db", "backend/test_bizassist.db"]:
        if os.path.exists(db_path):
            try:
                os.remove(db_path)
            except Exception:
                pass

from database.db import SessionLocal
from database.models import User, Product, Customer, Invoice, InvoicePayment, Expense
from core.stock import ledger as SL

client = TestClient(app)


@pytest.fixture(scope="module")
def auth_owner():
    """Sign up a business owner (non-cashier role)."""
    username = f"owner_{uuid.uuid4().hex[:8]}"
    resp = client.post("/signup", json={
        "username": username, "password": "TestPass123!", "business_name": "Owner Biz"
    })
    assert resp.status_code == 200
    body = resp.json()
    return {"headers": {"Authorization": f"Bearer {body['token']}"}, "bid": body["id"]}


@pytest.fixture(scope="module")
def auth_cashier():
    """Sign up a user and change their role to cashier in the DB."""
    username = f"cashier_{uuid.uuid4().hex[:8]}"
    resp = client.post("/signup", json={
        "username": username, "password": "TestPass123!", "business_name": "Cashier Biz"
    })
    assert resp.status_code == 200
    body = resp.json()
    bid = body["id"]

    # Update role to cashier in DB
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == bid).first()
        user.role = "cashier"
        db.commit()
    finally:
        db.close()

    # Re-sign the JWT with cashier role so it decodes with role="cashier"
    from services.auth import create_access_token
    token = create_access_token({
        "id": bid,
        "username": username,
        "business_name": "Cashier Biz",
        "role": "cashier"
    })

    return {"headers": {"Authorization": f"Bearer {token}"}, "bid": bid}


# ─── 1. Products CRUD ──────────────────────────────────────────────────────────

def test_products_crud(auth_owner):
    headers = auth_owner["headers"]
    
    # Create
    resp = client.post("/products", headers=headers, json={
        "name": "Organic Dal",
        "sku": "DAL_ORG_1",
        "barcode": "8901111222",
        "selling_price": 120.0,
        "cost_price": 95.0,
    })
    assert resp.status_code == 201, resp.text
    p = resp.json()
    pid = p["id"]
    assert p["name"] == "Organic Dal"
    assert p["sku"] == "DAL_ORG_1"

    # Read
    got = client.get(f"/products/{pid}", headers=headers)
    assert got.status_code == 200
    assert got.json()["name"] == "Organic Dal"

    # Update
    patch_resp = client.patch(f"/products/{pid}", headers=headers, json={
        "selling_price": 130.0,
        "description": "Premium organic dal"
    })
    assert patch_resp.status_code == 200
    assert patch_resp.json()["selling_price"] == 130.0
    assert patch_resp.json()["description"] == "Premium organic dal"

    # Add Barcode
    bc_resp = client.post(f"/products/{pid}/barcodes", headers=headers, json={
        "barcode": "8901111223",
        "make_primary": True
    })
    assert bc_resp.status_code == 201
    assert bc_resp.json()["is_primary"] is True


# ─── 2. Product Stock Adjustments ──────────────────────────────────────────────

def test_product_stock_adjustment(auth_owner):
    headers = auth_owner["headers"]
    
    # Create product
    resp = client.post("/products", headers=headers, json={
        "name": "Stock Item",
        "selling_price": 50.0,
    })
    pid = resp.json()["id"]

    # Adjust stock +10
    adj1 = client.post(f"/products/{pid}/stock/adjustment", headers=headers, json={
        "qty_delta": 10.0,
        "note": "opening batch"
    })
    assert adj1.status_code == 201
    assert adj1.json()["balance_after"] == 10.0

    # Adjust stock -3
    adj2 = client.post(f"/products/{pid}/stock/adjustment", headers=headers, json={
        "qty_delta": -3.0,
        "note": "damaged stock"
    })
    assert adj2.status_code == 201
    assert adj2.json()["balance_after"] == 7.0

    # Read stock state
    stock_resp = client.get(f"/products/{pid}/stock", headers=headers)
    assert stock_resp.status_code == 200
    res = stock_resp.json()
    assert res["current_stock"] == 7.0
    assert len(res["movements"]) == 2


# ─── 3. Customers & Vendors CRUD ───────────────────────────────────────────────

def test_customers_vendors_crud(auth_owner):
    headers = auth_owner["headers"]

    # Customer Create
    c_resp = client.post("/customers", headers=headers, json={
        "name": "Star Supermarket",
        "gstin": "29AAAAA1111A1Z1",
        "phone": "9876543210",
        "credit_days": 15
    })
    assert c_resp.status_code == 201
    cid = c_resp.json()["id"]

    # Customer Read
    c_got = client.get(f"/customers/{cid}", headers=headers)
    assert c_got.status_code == 200
    assert c_got.json()["name"] == "Star Supermarket"
    assert c_got.json()["outstanding_dues"] == 0.0

    # Vendor Create
    v_resp = client.post("/vendors", headers=headers, json={
        "name": "Hindustan Distributors",
        "gstin": "29BBBBB2222B2Z2",
        "payment_terms_days": 45
    })
    assert v_resp.status_code == 201
    vid = v_resp.json()["id"]

    # Vendor Update
    v_patch = client.patch(f"/vendors/{vid}", headers=headers, json={
        "phone": "9988776655"
    })
    assert v_patch.status_code == 200
    assert v_patch.json()["phone"] == "9988776655"


# ─── 4. Payments API ───────────────────────────────────────────────────────────

def test_payments_api(auth_owner):
    headers = auth_owner["headers"]
    bid = auth_owner["bid"]

    # Seed product & customer
    db = SessionLocal()
    try:
        p = Product(business_id=bid, name="Payable Item", selling_price=100, track_inventory=False, cgst_rate=9.0, sgst_rate=9.0)
        c = Customer(business_id=bid, name="Payer Cust")
        db.add(p)
        db.add(c)
        db.commit()
        pid = p.id
        cid = c.id
    finally:
        db.close()

    # Create Invoice (requires ₹118.00 total: ₹100 subtotal + 18% GST)
    inv_resp = client.post("/sales", headers=headers, json={
        "place_of_supply": "29",
        "customer_id": cid,
        "paid_amount": 0.0,
        "lines": [{"product_id": pid, "quantity": 1, "unit_price": 100}]
    })
    assert inv_resp.status_code == 200
    inv = inv_resp.json()
    inv_db_id = inv["id"]

    # Record partial payment of ₹50
    idem_key = f"idem-{uuid.uuid4().hex}"
    p_resp = client.post("/payments", headers=headers, json={
        "invoice_id": inv_db_id,
        "amount_paid": 50.0,
        "payment_mode": "UPI",
        "idempotency_key": idem_key
    })
    assert p_resp.status_code == 201
    assert p_resp.json()["amount_paid"] == 50.0

    # Idempotency check (retry same key)
    p_retry = client.post("/payments", headers=headers, json={
        "invoice_id": inv_db_id,
        "amount_paid": 50.0,
        "payment_mode": "UPI",
        "idempotency_key": idem_key
    })
    assert p_retry.status_code == 201
    assert p_retry.json()["id"] == p_resp.json()["id"] # same payment ID returned

    # Validate customer ledger reflecting outstanding
    ledger = client.get(f"/customers/{cid}/ledger", headers=headers)
    assert ledger.status_code == 200
    assert ledger.json()["entries"][0]["paid_amount"] == 50.0
    assert ledger.json()["entries"][0]["outstanding"] == 68.0 # 118.0 - 50.0


def test_expense_delete_is_blocked_append_only(auth_owner):
    """Expenses feed the books, so DELETE must not physically remove them."""
    headers = auth_owner["headers"]
    bid = auth_owner["bid"]

    created = client.post("/expenses", headers=headers, json={
        "expense_date": "2026-07-02",
        "category": "Rent",
        "expense_type": "Indirect",
        "amount": 1200.0,
        "payment_mode": "Cash",
        "note": "monthly shop rent",
    })
    assert created.status_code == 201, created.text
    expense_id = created.json()["id"]

    deleted = client.delete(f"/expenses/{expense_id}", headers=headers)
    assert deleted.status_code == 405
    assert "append-only" in deleted.json()["detail"].lower()

    db = SessionLocal()
    try:
        exp = db.query(Expense).filter(Expense.id == expense_id, Expense.business_id == bid).first()
        assert exp is not None
        assert exp.amount == 1200.0
    finally:
        db.close()


# ─── 5. Credit Notes API ───────────────────────────────────────────────────────

def test_credit_note_api(auth_owner):
    headers = auth_owner["headers"]
    bid = auth_owner["bid"]

    # Seed product & customer with stock tracking
    db = SessionLocal()
    try:
        p = Product(business_id=bid, name="CN Item", selling_price=100, track_inventory=True, cgst_rate=9.0, sgst_rate=9.0)
        c = Customer(business_id=bid, name="CN Cust")
        db.add(p)
        db.add(c)
        db.commit()
        pid = p.id
        cid = c.id
        # record initial stock of 10
        SL.record_movement(db, business_id=bid, movement_type=SL.OPENING, qty_delta=10, product_id=pid, product_name="CN Item")
        db.commit()
    finally:
        db.close()

    # Create Sale of 3 items (stock goes to 7)
    inv_resp = client.post("/sales", headers=headers, json={
        "place_of_supply": "29",
        "customer_id": cid,
        "paid_amount": 354.0, # fully paid: 3 * 100 * 1.18 = 354
        "lines": [{"product_id": pid, "quantity": 3, "unit_price": 100}]
    })
    inv_db_id = inv_resp.json()["id"]

    # Create Credit Note returning 1 item
    cn_resp = client.post("/credit-notes", headers=headers, json={
        "invoice_id": inv_db_id,
        "lines": [
            {
                "product_id": pid,
                "product_name": "CN Item",
                "quantity": 1,
                "unit_price": 100,
                "cgst_rate": 9.0,
                "sgst_rate": 9.0,
            }
        ],
        "note": "item returned by client"
    })
    assert cn_resp.status_code == 201
    cn = cn_resp.json()
    assert cn["invoice_type"] == "credit_note"
    assert cn["total_amount"] == 118.0

    # Verify stock returned to 8 (7 + 1)
    stock_resp = client.get(f"/products/{pid}/stock", headers=headers)
    assert stock_resp.json()["current_stock"] == 8.0


def test_credit_note_tenant_isolation(auth_owner):
    """A different business CANNOT create a credit note against another's invoice."""
    headers = auth_owner["headers"]
    bid = auth_owner["bid"]
    db = SessionLocal()
    try:
        p = Product(business_id=bid, name="Iso Item", selling_price=100, track_inventory=True, cgst_rate=9.0, sgst_rate=9.0)
        db.add(p); db.commit(); pid = p.id
    finally:
        db.close()
    inv_db_id = client.post("/sales", headers=headers, json={
        "place_of_supply": "29", "paid_amount": 118.0,
        "lines": [{"product_id": pid, "quantity": 1, "unit_price": 100}],
    }).json()["id"]

    # A second, unrelated business signs up
    uname = f"ownerB_{uuid.uuid4().hex[:8]}"
    b = client.post("/signup", json={"username": uname, "password": "TestPass123!", "business_name": "Other Biz"}).json()
    headers_b = {"Authorization": f"Bearer {b['token']}"}

    # ...and tries to credit-note business A's invoice → rejected (not their invoice)
    resp = client.post("/credit-notes", headers=headers_b, json={
        "invoice_id": inv_db_id,
        "lines": [{"product_id": pid, "product_name": "Iso Item", "quantity": 1,
                   "unit_price": 100, "cgst_rate": 9.0, "sgst_rate": 9.0}],
    })
    assert resp.status_code in (403, 404, 422)


def test_invoice_pdf_route(auth_owner):
    """The print/PDF endpoint returns content (PDF via WeasyPrint, else HTML fallback)."""
    headers = auth_owner["headers"]
    bid = auth_owner["bid"]
    db = SessionLocal()
    try:
        p = Product(business_id=bid, name="PDF Item", selling_price=100, track_inventory=True, cgst_rate=9.0, sgst_rate=9.0)
        db.add(p); db.commit(); pid = p.id
    finally:
        db.close()
    inv_db_id = client.post("/sales", headers=headers, json={
        "place_of_supply": "29", "paid_amount": 118.0,
        "lines": [{"product_id": pid, "quantity": 1, "unit_price": 100}],
    }).json()["id"]
    db = SessionLocal()
    try:
        invoice_no = db.query(Invoice).filter(Invoice.id == inv_db_id).first().invoice_id
    finally:
        db.close()

    resp = client.get(f"/sales/{invoice_no}/pdf", headers=headers)
    assert resp.status_code == 200
    assert len(resp.content) > 0
    ctype = resp.headers.get("content-type", "")
    if "html" in ctype:
        assert invoice_no in resp.text          # HTML fallback must name the invoice
    else:
        assert ctype.startswith("application/pdf")


def test_invoice_pdf_404_for_missing(auth_owner):
    resp = client.get("/sales/NOPE-9999/pdf", headers=auth_owner["headers"])
    assert resp.status_code == 404


# ─── 6. Reports & Analytics ────────────────────────────────────────────────────

def test_reports_api(auth_owner):
    headers = auth_owner["headers"]
    today = datetime.today().strftime("%Y-%m-%d")

    # Fetch day summary report
    summary = client.get(f"/reports/day-summary?date={today}", headers=headers)
    assert summary.status_code == 200
    res = summary.json()
    assert res["date"] == today
    assert "total_sales" in res
    assert "total_collections" in res
    assert "gst_summary" in res

    # Fetch overall stock ledger
    ledger = client.get("/stock/ledger", headers=headers)
    assert ledger.status_code == 200
    assert len(ledger.json()) > 0


# ─── 7. Bulk Imports ───────────────────────────────────────────────────────────

def test_bulk_imports(auth_owner):
    headers = auth_owner["headers"]

    # Import products bulk
    p_import = client.post("/import/products", headers=headers, json={
        "items": [
            {
                "name": "Imported Rice",
                "sku": "IMP-RICE-1",
                "barcode": "8908887776",
                "selling_price": 80,
                "opening_stock": 25
            },
            {
                "name": "Imported Dal",
                "sku": "IMP-DAL-1",
                "selling_price": 110,
                "opening_stock": 0
            }
        ]
    })
    assert p_import.status_code == 200
    assert p_import.json()["created"] == 2

    # Import customers bulk
    c_import = client.post("/import/customers", headers=headers, json={
        "items": [
            {
                "name": "Bulk Customer A",
                "phone": "9998887776",
                "opening_dues": 1500
            }
        ]
    })
    assert c_import.status_code == 200
    assert c_import.json()["created"] == 1


# ─── 8. Cashier RBAC ───────────────────────────────────────────────────────────

def test_cashier_rbac_restrictions(auth_cashier):
    headers = auth_cashier["headers"]

    # Cashier CAN search products
    resp_search = client.get("/sales/products/search?q=Rice", headers=headers)
    assert resp_search.status_code == 200

    # Cashier CANNOT view reports
    today = datetime.today().strftime("%Y-%m-%d")
    resp_report = client.get(f"/reports/day-summary?date={today}", headers=headers)
    assert resp_report.status_code == 403

    # Cashier CANNOT create credit notes
    resp_cn = client.post("/credit-notes", headers=headers, json={
        "invoice_id": 999,
        "lines": []
    })
    assert resp_cn.status_code == 403

    # Cashier CANNOT perform imports
    resp_imp = client.post("/import/products", headers=headers, json={"items": []})
    assert resp_imp.status_code == 403
