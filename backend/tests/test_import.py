import os
import sys
import uuid
import csv
import io
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
from database.models import Base, Product, Customer, Vendor, Invoice, User, Inventory
from core.models import StockLedger, ProductBarcode, InvoicePayment
from core.stock import ledger as SL

client = TestClient(app)


@pytest.fixture(scope="module", autouse=True)
def _ensure_db_schema():
    # Runs once per module to clean up DB file and setup schema
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
    # Create Business A owner via signup
    resp_a = client.post("/signup", json={"username": f"ownera_{uuid.uuid4().hex[:6]}", "password": "Password123!", "business_name": "Biz A"})
    assert resp_a.status_code == 200, resp_a.text
    data_a = resp_a.json()
    token_a = data_a["token"]
    bid_a = data_a["id"]

    # Create Business B owner via signup
    resp_b = client.post("/signup", json={"username": f"ownerb_{uuid.uuid4().hex[:6]}", "password": "Password123!", "business_name": "Biz B"})
    assert resp_b.status_code == 200, resp_b.text
    data_b = resp_b.json()
    token_b = data_b["token"]
    bid_b = data_b["id"]

    # Create Business A cashier via /staff endpoint using owner_a headers
    headers_a = {"Authorization": f"Bearer {token_a}"}
    resp_cashier = client.post("/staff", headers=headers_a, json={"username": f"cashier_{uuid.uuid4().hex[:6]}", "password": "Password123!", "role": "cashier"})
    assert resp_cashier.status_code == 201, resp_cashier.text
    cashier_username = resp_cashier.json()["username"]

    # Log in as cashier to get their token
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
    # Clear all data tables before each test function, but keep User records
    db = SessionLocal()
    try:
        db.query(InvoicePayment).delete()
        db.query(Invoice).delete()
        db.query(StockLedger).delete()
        db.query(ProductBarcode).delete()
        db.query(Inventory).delete()
        db.query(Product).delete()
        db.query(Customer).delete()
        db.query(Vendor).delete()
        db.commit()
    finally:
        db.close()


# ── Bulk Imports Tests ────────────────────────────────────────────────────────

def test_import_products_json(api_auth):
    payload = {
        "items": [
            {
                "name": "Imported Product 1",
                "sku": "SKU-IMP-1",
                "barcode": "111222333444",
                "selling_price": 99.9,
                "cost_price": 60.0,
                "mrp": 120.0,
                "cgst_rate": 9.0,
                "sgst_rate": 9.0,
                "opening_stock": 25.0
            },
            {
                "name": "Imported Product 2",
                "sku": "SKU-IMP-2",
                "selling_price": 10.0,
                "cost_price": 5.0
            }
        ]
    }

    resp = client.post("/import/products", headers=api_auth["owner_a"], json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["created"] == 2
    assert len(data["errors"]) == 0

    db = SessionLocal()
    try:
        # Check Product 1
        p1 = db.query(Product).filter(Product.business_id == api_auth["bid_a"], Product.sku == "SKU-IMP-1").first()
        assert p1 is not None
        assert p1.name == "Imported Product 1"
        assert p1.selling_price == 99.9
        assert p1.mrp == 120.0
        assert p1.cgst_rate == 9.0

        # Check Product 1 barcode
        bc = db.query(ProductBarcode).filter(ProductBarcode.business_id == api_auth["bid_a"], ProductBarcode.product_id == p1.id).first()
        assert bc is not None
        assert bc.barcode == "111222333444"

        # Check Product 1 Stock ledger and cache
        ledger_moves = db.query(StockLedger).filter(StockLedger.business_id == api_auth["bid_a"], StockLedger.product_id == p1.id).all()
        assert len(ledger_moves) == 1
        assert ledger_moves[0].movement_type == SL.OPENING
        assert ledger_moves[0].qty_delta == 25.0

        cache = db.query(Inventory).filter(Inventory.business_id == api_auth["bid_a"], Inventory.product_id == p1.id).first()
        assert cache is not None
        assert cache.stock == 25.0

        # SKU duplicate check within business A
        dup_payload = {
            "items": [
                {
                    "name": "Duplicate SKU Product",
                    "sku": "SKU-IMP-1",
                    "selling_price": 15.0
                }
            ]
        }
        dup_resp = client.post("/import/products", headers=api_auth["owner_a"], json=dup_payload)
        assert dup_resp.status_code == 200
        dup_data = dup_resp.json()
        assert dup_data["created"] == 0
        assert len(dup_data["errors"]) == 1
        assert "already exists" in dup_data["errors"][0]

    finally:
        db.close()


def test_import_products_csv(api_auth):
    csv_data = (
        "name,sku,barcode,selling_price,cost_price,mrp,cgst_rate,sgst_rate,opening_stock\n"
        "CSV Product 1,SKU-CSV-1,999888777,45.0,30.0,50.0,6.0,6.0,15.0\n"
        "CSV Product 2,SKU-CSV-2,,100.0,80.0,,,,\n"
    )
    
    file_payload = {"file": ("products.csv", csv_data.encode("utf-8"), "text/csv")}
    
    resp = client.post("/import/products", headers=api_auth["owner_a"], files=file_payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["created"] == 2
    assert len(data["errors"]) == 0

    db = SessionLocal()
    try:
        p = db.query(Product).filter(Product.business_id == api_auth["bid_a"], Product.sku == "SKU-CSV-1").first()
        assert p is not None
        assert p.name == "CSV Product 1"
        assert p.cost_price == 30.0
        
        # Verify barcode
        bc = db.query(ProductBarcode).filter(ProductBarcode.business_id == api_auth["bid_a"], ProductBarcode.product_id == p.id).first()
        assert bc is not None
        assert bc.barcode == "999888777"

        # Verify stock movement and inventory cache
        cache = db.query(Inventory).filter(Inventory.business_id == api_auth["bid_a"], Inventory.product_id == p.id).first()
        assert cache is not None
        assert cache.stock == 15.0
    finally:
        db.close()


def test_import_customers_and_vendors(api_auth):
    # Customer JSON import with opening_dues
    cust_payload = {
        "items": [
            {
                "name": "Jane Doe",
                "phone": "9876543210",
                "email": "jane@example.com",
                "address": "123 Street",
                "gstin": "29ABCDE1234F1Z5",
                "opening_dues": 500.0
            }
        ]
    }
    cust_resp = client.post("/import/customers", headers=api_auth["owner_a"], json=cust_payload)
    assert cust_resp.status_code == 200
    cust_data = cust_resp.json()
    assert cust_data["created"] == 1

    # Vendor JSON import
    vendor_payload = {
        "items": [
            {
                "name": "Supplier X",
                "phone": "8765432109",
                "email": "vendor@example.com",
                "payment_terms_days": 45
            }
        ]
    }
    v_resp = client.post("/import/vendors", headers=api_auth["owner_a"], json=vendor_payload)
    assert v_resp.status_code == 200
    assert v_resp.json()["created"] == 1

    db = SessionLocal()
    try:
        # Check Customer was created
        cust = db.query(Customer).filter(Customer.business_id == api_auth["bid_a"], Customer.name == "Jane Doe").first()
        assert cust is not None
        assert cust.phone == "9876543210"

        # Check opening dues invoice was recorded (append-only outstanding check)
        inv = db.query(Invoice).filter(Invoice.business_id == api_auth["bid_a"], Invoice.customer_id == cust.id).first()
        assert inv is not None
        assert inv.invoice_type == "opening_due"
        assert inv.total_amount == 500.0
        assert inv.status == "Pending"

        # Check Vendor was created
        vend = db.query(Vendor).filter(Vendor.business_id == api_auth["bid_a"], Vendor.name == "Supplier X").first()
        assert vend is not None
        assert vend.payment_terms_days == 45
    finally:
        db.close()


# ── Tenant Isolation and RBAC Tests ───────────────────────────────────────────

def test_import_endpoints_cashier_restricted(api_auth):
    # Cashiers should receive 403 Forbidden on import routes
    resp_prod = client.post("/import/products", headers=api_auth["cashier_a"], json={"items": []})
    assert resp_prod.status_code == 403

    resp_cust = client.post("/import/customers", headers=api_auth["cashier_a"], json={"items": []})
    assert resp_cust.status_code == 403

    resp_vend = client.post("/import/vendors", headers=api_auth["cashier_a"], json={"items": []})
    assert resp_vend.status_code == 403


def test_import_tenant_isolation(api_auth):
    # Import products for Business A
    payload_a = {"items": [{"name": "A Product", "sku": "SKU-A", "selling_price": 50.0}]}
    client.post("/import/products", headers=api_auth["owner_a"], json=payload_a)

    # Import products for Business B
    payload_b = {"items": [{"name": "B Product", "sku": "SKU-B", "selling_price": 100.0}]}
    client.post("/import/products", headers=api_auth["owner_b"], json=payload_b)

    db = SessionLocal()
    try:
        # Business A should NOT have SKU-B
        p_a = db.query(Product).filter(Product.business_id == api_auth["bid_a"], Product.sku == "SKU-B").first()
        assert p_a is None

        # Business B should NOT have SKU-A
        p_b = db.query(Product).filter(Product.business_id == api_auth["bid_b"], Product.sku == "SKU-A").first()
        assert p_b is None
    finally:
        db.close()


# ── Bulk Exports Tests ────────────────────────────────────────────────────────

def test_exports_tenant_scoping(api_auth):
    db = SessionLocal()
    try:
        # Seed Products for A and B
        p_a = Product(business_id=api_auth["bid_a"], name="Prod A", sku="SKU-A", selling_price=10.0, track_inventory=True)
        p_b = Product(business_id=api_auth["bid_b"], name="Prod B", sku="SKU-B", selling_price=20.0, track_inventory=True)
        db.add_all([p_a, p_b])
        db.commit()

        # Seed Invoice and Payment for A
        inv = Invoice(business_id=api_auth["bid_a"], invoice_id="INV-A1", customer="Walkin", amount=150.0, total_amount=150.0, paid_amount=150.0, status="Paid")
        db.add(inv)
        db.flush()

        payment = InvoicePayment(business_id=api_auth["bid_a"], invoice_id=inv.id, amount_paid=150.0, payment_mode="Cash", payment_date="2026-06-20")
        db.add(payment)

        # Seed Stock Ledger entry for A
        SL.record_movement(db, business_id=api_auth["bid_a"], movement_type=SL.SALE, qty_delta=-2.0, product_id=p_a.id, product_name=p_a.name)
        db.commit()

        # Export Products for A
        resp_prod = client.get("/export/products", headers=api_auth["owner_a"])
        assert resp_prod.status_code == 200
        assert resp_prod.headers["content-type"] == "text/csv; charset=utf-8"
        prod_reader = csv.reader(io.StringIO(resp_prod.text))
        rows = list(prod_reader)
        # Header + Prod A (Prod B must be absent)
        assert len(rows) == 2
        assert rows[1][0] == "Prod A"
        assert rows[1][1] == "SKU-A"

        # Export Invoices for A
        resp_inv = client.get("/export/invoices", headers=api_auth["owner_a"])
        assert resp_inv.status_code == 200
        inv_reader = csv.reader(io.StringIO(resp_inv.text))
        inv_rows = list(inv_reader)
        assert len(inv_rows) == 2
        assert inv_rows[1][0] == "INV-A1"

        # Export Payments for A
        resp_pay = client.get("/export/payments", headers=api_auth["owner_a"])
        assert resp_pay.status_code == 200
        pay_reader = csv.reader(io.StringIO(resp_pay.text))
        pay_rows = list(pay_reader)
        assert len(pay_rows) == 2
        assert pay_rows[1][0] == "2026-06-20"
        assert pay_rows[1][3] == "150.0"

        # Export Stock Ledger for A
        resp_sl = client.get("/export/stock-ledger", headers=api_auth["owner_a"])
        assert resp_sl.status_code == 200
        sl_reader = csv.reader(io.StringIO(resp_sl.text))
        sl_rows = list(sl_reader)
        # Header + SALE movement (Prod B should not appear in A's export)
        assert len(sl_rows) == 2
        assert sl_rows[1][1] == "Prod A"
        assert sl_rows[1][2] == SL.SALE
        assert sl_rows[1][3] == "-2.0"

    finally:
        db.close()
