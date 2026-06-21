import os
import sys
import uuid
from datetime import datetime

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, backend_path)

db_file = os.path.join(backend_path, "test_bizassist.db").replace("\\", "/")
os.environ["DATABASE_URL"] = f"sqlite:///{db_file}"
os.environ["GROQ_API_KEY"] = "mock_groq_api_key"

import pytest
from fastapi.testclient import TestClient
from main_groq import app
from database.db import SessionLocal
from database.models import Base, Product, Customer, Vendor, PurchaseInvoice, PurchaseInvoiceLineItem, User, Inventory
from core.models import StockLedger, ProductBarcode
from core.stock import ledger as SL

client = TestClient(app)


@pytest.fixture(scope="module", autouse=True)
def _ensure_db_schema():
    if os.path.exists(db_file):
        try:
            os.remove(db_file)
        except Exception:
            pass
    db = SessionLocal()
    try:
        bind = db.get_bind()
        Base.metadata.create_all(bind=bind)
    finally:
        db.close()


@pytest.fixture(scope="module")
def api_auth():
    # Business A owner
    resp_a = client.post("/signup", json={"username": f"ownera_{uuid.uuid4().hex[:6]}", "password": "Password123!", "business_name": "Biz A"})
    assert resp_a.status_code == 200, resp_a.text
    data_a = resp_a.json()
    token_a = data_a["token"]
    bid_a = data_a["id"]

    # Business B owner
    resp_b = client.post("/signup", json={"username": f"ownerb_{uuid.uuid4().hex[:6]}", "password": "Password123!", "business_name": "Biz B"})
    assert resp_b.status_code == 200, resp_b.text
    data_b = resp_b.json()
    token_b = data_b["token"]
    bid_b = data_b["id"]

    # Business A cashier
    headers_a = {"Authorization": f"Bearer {token_a}"}
    resp_cashier = client.post("/staff", headers=headers_a, json={"username": f"cashier_{uuid.uuid4().hex[:6]}", "password": "Password123!", "role": "cashier"})
    assert resp_cashier.status_code == 201, resp_cashier.text
    cashier_username = resp_cashier.json()["username"]

    # Cashier A login
    resp_login = client.post("/login", json={"username": cashier_username, "password": "Password123!"})
    assert resp_login.status_code == 200, resp_login.text
    token_cashier_a = resp_login.json()["token"]

    return {
        "owner_a": headers_a,
        "owner_b": {"Authorization": f"Bearer {token_b}"},
        "cashier_a": {"Authorization": f"Bearer {token_cashier_a}"},
        "bid_a": bid_a,
        "bid_b": bid_b,
    }


@pytest.fixture(autouse=True)
def _setup(api_auth):
    db = SessionLocal()
    try:
        db.query(PurchaseInvoiceLineItem).delete()
        db.query(PurchaseInvoice).delete()
        db.query(StockLedger).delete()
        db.query(ProductBarcode).delete()
        db.query(Inventory).delete()
        db.query(Product).delete()
        db.query(Customer).delete()
        db.query(Vendor).delete()
        db.commit()
    finally:
        db.close()


# ── Purchase Confirmation Tests ──────────────────────────────────────────────

def test_confirm_purchase_invoice_creates_and_updates_entities(api_auth):
    db = SessionLocal()
    try:
        # Pre-seed an existing product in Business A to test cost price updates
        existing_p = Product(
            business_id=api_auth["bid_a"],
            name="Existing product",
            cost_price=100.0,
            selling_price=150.0,
            unit="Nos",
            track_inventory=True
        )
        db.add(existing_p)
        db.commit()
        db.refresh(existing_p)
        existing_p_id = existing_p.id
    finally:
        db.close()

    confirm_payload = {
        "supplier_name": "Acme Pharma",
        "invoice_number": "INV-2026-001",
        "invoice_date": "2026-06-20",
        "due_date": "2026-07-20",
        "status": "Pending",
        "notes": "Fast shipping",
        "subtotal": 1200.0,
        "cgst_total": 60.0,
        "sgst_total": 60.0,
        "total_amount": 1320.0,
        "items": [
            {
                "product_id": existing_p_id,
                "product_name": "Existing product",
                "quantity": 10.0,
                "unit": "Nos",
                "unit_price": 80.0, # Price dropped 100 -> 80
                "cgst_rate": 5.0,
                "sgst_rate": 5.0,
                "taxable_value": 800.0,
                "cgst_amount": 40.0,
                "sgst_amount": 40.0,
                "line_total": 880.0,
                "batch": "BT-999",
                "expiry": "2028-12-31"
            },
            {
                "product_name": "Newly Discovered Product",
                "quantity": 2.0,
                "unit": "Box",
                "purchase_unit": "Box",
                "conversion_factor": 10.0, # 1 Box = 10 pieces
                "unit_price": 200.0,
                "cgst_rate": 5.0,
                "sgst_rate": 5.0,
                "taxable_value": 400.0,
                "cgst_amount": 20.0,
                "sgst_amount": 20.0,
                "line_total": 440.0,
                "barcode": "BARCODE-NEW-123",
                "batch": "BT-888"
            }
        ]
    }

    # Post to confirm endpoint
    resp = client.post("/purchases/confirm", headers=api_auth["owner_a"], json=confirm_payload)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["id"] is not None
    assert data["invoice_number"] == "INV-2026-001"
    assert data["supplier_name"] == "Acme Pharma"

    # Verify database updates
    db = SessionLocal()
    try:
        # 1. Product cost price update
        p = db.query(Product).filter(Product.id == existing_p_id).first()
        assert p.cost_price == 80.0

        # 2. Newly created product
        p_new = db.query(Product).filter(Product.name == "Newly Discovered Product", Product.business_id == api_auth["bid_a"]).first()
        assert p_new is not None
        assert p_new.cost_price == 200.0
        assert p_new.conversion_factor == 10.0

        # 3. Barcode association
        barcode = db.query(ProductBarcode).filter(ProductBarcode.barcode == "BARCODE-NEW-123", ProductBarcode.business_id == api_auth["bid_a"]).first()
        assert barcode is not None
        assert barcode.product_id == p_new.id

        # 4. Stock ledger movement
        # Line 1: Existing Product (conversion factor = 1.0, qty = 10.0) -> +10
        move1 = db.query(StockLedger).filter(StockLedger.product_id == existing_p_id, StockLedger.movement_type == SL.PURCHASE).first()
        assert move1 is not None
        assert move1.qty_delta == 10.0
        assert move1.batch_no == "BT-999"

        # Line 2: New Product (conversion factor = 10.0, qty = 2.0 Box) -> +20 pieces
        move2 = db.query(StockLedger).filter(StockLedger.product_id == p_new.id, StockLedger.movement_type == SL.PURCHASE).first()
        assert move2 is not None
        assert move2.qty_delta == 20.0 # 2 * 10
        assert move2.batch_no == "BT-888"

        # 5. Inventory cache scoped by batch
        inv1 = db.query(Inventory).filter(Inventory.product_id == existing_p_id, Inventory.batch_no == "BT-999").first()
        assert inv1 is not None
        assert inv1.stock == 10.0

        inv2 = db.query(Inventory).filter(Inventory.product_id == p_new.id, Inventory.batch_no == "BT-888").first()
        assert inv2 is not None
        assert inv2.stock == 20.0
    finally:
        db.close()


# ── Idempotency Verification ──────────────────────────────────────────────────

def test_confirm_idempotency(api_auth):
    payload = {
        "supplier_name": "Idempotent supplier",
        "invoice_number": "PUR-IDEM-007",
        "subtotal": 100.0,
        "total_amount": 100.0,
        "items": [
            {
                "product_name": "Idempotent product",
                "quantity": 1.0,
                "unit_price": 100.0,
                "line_total": 100.0
            }
        ]
    }

    # First attempt: success
    resp1 = client.post("/purchases/confirm", headers=api_auth["owner_a"], json=payload)
    assert resp1.status_code == 200

    # Second attempt: fails with duplicate validation error (422)
    resp2 = client.post("/purchases/confirm", headers=api_auth["owner_a"], json=payload)
    assert resp2.status_code == 422
    assert "already been processed" in resp2.json()["detail"]


# ── Tenant Isolation & Security Tests ────────────────────────────────────────

def test_tenant_isolation_endpoints(api_auth):
    # 1. Create a purchase invoice under Business A
    payload_a = {
        "supplier_name": "Supplier A",
        "invoice_number": "INV-A-100",
        "total_amount": 500.0,
        "items": [{"product_name": "Product A", "quantity": 5.0, "unit_price": 100.0, "line_total": 500.0}]
    }
    resp_create = client.post("/purchases/confirm", headers=api_auth["owner_a"], json=payload_a)
    assert resp_create.status_code == 200
    inv_a_id = resp_create.json()["id"]

    # 2. Business B owner attempts to view Business A's purchase detail -> 404 Not Found
    resp_get = client.get(f"/purchases/{inv_a_id}", headers=api_auth["owner_b"])
    assert resp_get.status_code == 404

    # 3. Business B owner lists purchases -> should NOT contain Business A's invoice
    resp_list_b = client.get("/purchases", headers=api_auth["owner_b"])
    assert resp_list_b.status_code == 200
    assert not any(x["id"] == inv_a_id for x in resp_list_b.json())

    # 4. Business A lists purchases -> should contain Business A's invoice
    resp_list_a = client.get("/purchases", headers=api_auth["owner_a"])
    assert resp_list_a.status_code == 200
    assert any(x["id"] == inv_a_id for x in resp_list_a.json())


def test_tenant_isolation_payload_hijack(api_auth):
    # Pre-seed a product in Business A
    db = SessionLocal()
    try:
        p_a = Product(business_id=api_auth["bid_a"], name="Secret Product A", cost_price=500.0)
        db.add(p_a)
        db.commit()
        db.refresh(p_a)
        p_a_id = p_a.id
    finally:
        db.close()

    # Business B owner attempts to confirm a purchase invoice using Business A's product ID
    payload_b = {
        "supplier_name": "Supplier B",
        "invoice_number": "INV-B-200",
        "items": [
            {
                "product_id": p_a_id, # Business A's product!
                "product_name": "Hijacked Product name",
                "quantity": 10.0,
                "unit_price": 50.0,
                "line_total": 500.0
            }
        ]
    }

    resp = client.post("/purchases/confirm", headers=api_auth["owner_b"], json=payload_b)
    assert resp.status_code == 200
    new_purchase = resp.json()
    new_line = new_purchase["lines"][0]

    # Verify that the system did NOT associate the purchase with Business A's product,
    # but instead created a new product scoped to Business B.
    assert new_line["product_id"] != p_a_id
    assert new_line["product_id"] is not None

    db = SessionLocal()
    try:
        # Verify Product A remains unmodified (cost_price=500.0, not 50.0)
        p_check = db.query(Product).filter(Product.id == p_a_id).first()
        assert p_check.cost_price == 500.0
        assert p_check.business_id == api_auth["bid_a"]

        # Verify a new product was created under Business B
        p_b_created = db.query(Product).filter(Product.id == new_line["product_id"]).first()
        assert p_b_created.business_id == api_auth["bid_b"]
        assert p_b_created.cost_price == 50.0
    finally:
        db.close()


def test_tenant_isolation_debit_note(api_auth):
    # 1. Create a purchase invoice under Business A
    payload_a = {
        "supplier_name": "Supplier A",
        "invoice_number": "INV-DEBIT-A",
        "total_amount": 1000.0,
        "items": [{"product_name": "Product A", "quantity": 10.0, "unit_price": 100.0, "line_total": 1000.0}]
    }
    resp_create = client.post("/purchases/confirm", headers=api_auth["owner_a"], json=payload_a)
    assert resp_create.status_code == 200
    inv_a_id = resp_create.json()["id"]
    p_a_id = resp_create.json()["lines"][0]["product_id"]

    # 2. Business B attempts to create a debit note referencing Business A's invoice -> should return 422
    dn_payload = {
        "original_purchase_id": inv_a_id,
        "debit_note_number": "DN-HIJACK-1",
        "lines": [{"product_id": p_a_id, "quantity": 1.0, "reason": "damaged"}],
        "note": "hijack attempt"
    }

    resp_dn = client.post("/purchases/debit-notes", headers=api_auth["owner_b"], json=dn_payload)
    assert resp_dn.status_code == 422
    assert "not found" in resp_dn.json()["detail"]
