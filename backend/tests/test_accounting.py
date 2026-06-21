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
from database.models import Base, Product, Customer, Vendor, PurchaseInvoice, User, Inventory, Expense
from core.models import StockLedger, InvoicePayment

client = TestClient(app)


@pytest.fixture(scope="session", autouse=True)
def cleanup_test_db():
    yield
    for db_path in [db_file]:
        if os.path.exists(db_path):
            try:
                os.remove(db_path)
            except Exception:
                pass


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

    # Log in cashier
    resp_login = client.post("/login", json={"username": cashier_username, "password": "Password123!"})
    assert resp_login.status_code == 200
    token_cashier = resp_login.json()["token"]

    return {
        "owner_a": {"Authorization": f"Bearer {token_a}"},
        "bid_a": bid_a,
        "owner_b": {"Authorization": f"Bearer {token_b}"},
        "bid_b": bid_b,
        "cashier_a": {"Authorization": f"Bearer {token_cashier}"}
    }


def test_accounting_endpoints_empty(api_auth):
    # Test endpoints return 0/empty for new business (Biz B)
    headers = api_auth["owner_b"]
    
    # Day book
    resp = client.get("/reports/day-book", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["transactions"] == []
    assert data["summary"]["total_sales"] == 0.0
    assert data["summary"]["total_purchases"] == 0.0
    assert data["summary"]["total_expenses"] == 0.0
    assert data["summary"]["total_receipts"] == 0.0
    assert data["summary"]["net_cash_flow"] == 0.0

    # Balance Sheet
    resp = client.get("/reports/balance-sheet", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["assets"]["cash_bank"] == 0.0
    assert data["assets"]["receivables"] == 0.0
    assert data["assets"]["inventory_valuation"] == 0.0
    assert data["assets"]["total_assets"] == 0.0
    assert data["liabilities"]["payables"] == 0.0
    assert data["liabilities"]["total_liabilities"] == 0.0
    assert data["net_worth"] == 0.0


def test_accounting_cashier_restricted(api_auth):
    # Cashiers are restricted from financial reports (403)
    headers = api_auth["cashier_a"]
    resp1 = client.get("/reports/day-book", headers=headers)
    assert resp1.status_code == 403
    resp2 = client.get("/reports/balance-sheet", headers=headers)
    assert resp2.status_code == 403


def test_accounting_depth_calculations(api_auth):
    headers = api_auth["owner_a"]
    bid = api_auth["bid_a"]
    today_str = datetime.today().strftime("%Y-%m-%d")

    # 1. Create a customer and vendor for Biz A
    c_resp = client.post("/customers", headers=headers, json={
        "name": "Cust A", "phone": "1234567890"
    })
    assert c_resp.status_code == 201
    cid = c_resp.json()["id"]

    v_resp = client.post("/vendors", headers=headers, json={
        "name": "Vend A", "phone": "0987654321"
    })
    assert v_resp.status_code == 201
    vid = v_resp.json()["id"]

    # 2. Create a product and set cost/stock
    p_resp = client.post("/products", headers=headers, json={
        "name": "Prod A", "selling_price": 100.0, "cost_price": 60.0, "sku": "P-A-1", "track_inventory": True
    })
    assert p_resp.status_code == 201
    pid = p_resp.json()["id"]

    # Seed Inventory explicitly (10 units @ cost 60.0 = 600.0 valuation)
    db = SessionLocal()
    try:
        inv = Inventory(business_id=bid, product_name="Prod A", product_id=pid, stock=10, cost_price=60.0, selling_price=100.0)
        db.add(inv)
        db.commit()
    finally:
        db.close()

    # 3. Create a Sale Invoice (Total = 118, paid = 0)
    # 100 base + 18% GST = 118
    sale_resp = client.post("/sales", headers=headers, json={
        "lines": [{
            "product_id": pid,
            "product_name": "Prod A",
            "quantity": 1.0,
            "unit_price": 100.0,
            "cgst_rate": 9.0,
            "sgst_rate": 9.0,
            "igst_rate": 0.0
        }],
        "customer": "Cust A",
        "customer_id": cid,
        "invoice_no": f"INV-{uuid.uuid4().hex[:6]}",
        "invoice_date": today_str,
        "paid_amount": 0.0,
        "payment_mode": "UPI"
    })
    assert sale_resp.status_code == 200, sale_resp.text
    invoice_db_id = sale_resp.json()["id"]

    # 4. Create a Purchase Invoice (Total = 120, Paid)
    confirm_payload_paid = {
        "supplier_name": "Vend A",
        "invoice_number": f"PUR-{uuid.uuid4().hex[:6]}",
        "invoice_date": today_str,
        "status": "Paid",
        "subtotal": 100.0,
        "cgst_total": 10.0,
        "sgst_total": 10.0,
        "total_amount": 120.0,
        "items": [{
            "product_id": pid,
            "product_name": "Prod A",
            "quantity": 2.0,
            "unit": "Nos",
            "unit_price": 50.0,
            "cgst_rate": 10.0,
            "sgst_rate": 10.0,
            "taxable_value": 100.0,
            "cgst_amount": 10.0,
            "sgst_amount": 10.0,
            "line_total": 120.0
        }]
    }
    pur_paid_resp = client.post("/purchases/confirm", headers=headers, json=confirm_payload_paid)
    assert pur_paid_resp.status_code == 200, pur_paid_resp.text

    # 5. Create a Purchase Invoice (Total = 240, Pending/Credit)
    confirm_payload_unpaid = {
        "supplier_name": "Vend A",
        "invoice_number": f"PUR-{uuid.uuid4().hex[:6]}",
        "invoice_date": today_str,
        "status": "Pending",
        "subtotal": 200.0,
        "cgst_total": 20.0,
        "sgst_total": 20.0,
        "total_amount": 240.0,
        "items": [{
            "product_id": pid,
            "product_name": "Prod A",
            "quantity": 4.0,
            "unit": "Nos",
            "unit_price": 50.0,
            "cgst_rate": 10.0,
            "sgst_rate": 10.0,
            "taxable_value": 200.0,
            "cgst_amount": 20.0,
            "sgst_amount": 20.0,
            "line_total": 240.0
        }]
    }
    pur_unpaid_resp = client.post("/purchases/confirm", headers=headers, json=confirm_payload_unpaid)
    assert pur_unpaid_resp.status_code == 200, pur_unpaid_resp.text

    # 6. Create an Expense (Amount = 30)
    exp_resp = client.post("/expenses", headers=headers, json={
        "expense_date": today_str,
        "category": "Office Rent",
        "expense_type": "Direct",
        "amount": 30.0,
        "payment_mode": "Cash"
    })
    assert exp_resp.status_code == 201

    # 7. Record payment of 50
    pay_resp1 = client.post("/payments", headers=headers, json={
        "invoice_id": invoice_db_id,
        "amount_paid": 50.0,
        "payment_mode": "UPI",
        "idempotency_key": f"idem-{uuid.uuid4().hex[:6]}"
    })
    assert pay_resp1.status_code == 201

    # 8. Record another payment of 25
    pay_resp2 = client.post("/payments", headers=headers, json={
        "invoice_id": invoice_db_id,
        "amount_paid": 25.0,
        "payment_mode": "UPI",
        "idempotency_key": f"idem-{uuid.uuid4().hex[:6]}"
    })
    assert pay_resp2.status_code == 201

    # --- Day Book Verification ---
    db_resp = client.get(f"/reports/day-book?from={today_str}&to={today_str}", headers=headers)
    assert db_resp.status_code == 200
    db_data = db_resp.json()
    
    # Check chronological transactions structure
    transactions = db_data["transactions"]
    assert len(transactions) >= 5 # Sale, Purchase Paid, Purchase Pending, Expense, Receipt/Payment
    
    # Check that they are sorted chronologically (all are today, so they should be grouped/sorted)
    # Check summary metrics
    summary = db_data["summary"]
    assert summary["total_sales"] == 118.0
    assert summary["total_purchases"] == 360.0 # 120 + 240
    assert summary["total_expenses"] == 30.0
    assert summary["total_receipts"] == 75.0 # InvoicePayment amount_paid (50 + 25)
    # net_cash_flow = total_receipts (75.0) - total_expenses (30.0) = 45.0
    assert summary["net_cash_flow"] == 45.0

    # --- Balance Sheet Verification ---
    bs_resp = client.get("/reports/balance-sheet", headers=headers)
    assert bs_resp.status_code == 200
    bs_data = bs_resp.json()

    # Calculation Rules:
    # 1. cash_bank = sales_receipts - purchase_payments - expense_payments
    #    sales_receipts: sum of Invoice.paid_amount.
    #    Wait! Let's check: the Invoice was created with paid_amount=50. Then a payment of 25 was recorded.
    #    Let's check the invoice paid_amount in DB.
    #    Invoice.paid_amount was updated to 75.0 when payment was saved.
    #    Let's check: sales_receipts = 75.0
    #    purchase_payments: sum of PurchaseInvoice.total_amount for status == "Paid".
    #    We had one Paid purchase invoice of 120.0.
    #    purchase_payments = 120.0
    #    expense_payments: sum of Expense.amount = 30.0.
    #    cash_bank = 75.0 - 120.0 - 30.0 = -75.0
    assert bs_data["assets"]["cash_bank"] == -75.0

    # 2. receivables = sum(Invoice.total_amount - Invoice.paid_amount)
    #    Invoice: total_amount = 118.0, paid_amount = 75.0.
    #    receivables = 118.0 - 75.0 = 43.0.
    assert bs_data["assets"]["receivables"] == 43.0

    # 3. inventory_valuation = stock * cost_price
    #    Inventory record created: stock = 10, cost_price = 60.0.
    #    valuation = 600.0.
    #    Wait, did the sale and purchase invoice modify the inventory stock/cost price?
    #    Let's verify what the final inventory valuation is.
    #    During a sale, stock might be reduced or not. Let's see: if we created an inventory item with stock=10.
    #    Wait, does `confirm_purchase_invoice` or `create_sale_invoice` automatically update the Inventory table's stock?
    #    Let's check: the purchases confirm endpoint:
    #    `accept_supplier_invoice` in `purchase_commands` updates inventory stock.
    #    Let's check if it does.
    #    Also, let's verify what the actual inventory valuation is in the response.
    #    Since it's in the response, we can assert it equals whatever the DB query returns or the seeded amount.
    db_test = SessionLocal()
    inventories = db_test.query(Inventory).filter(Inventory.business_id == bid).all()
    expected_inventory_val = sum((item.stock or 0.0) * (item.cost_price or 0.0) for item in inventories)
    db_test.close()

    assert bs_data["assets"]["inventory_valuation"] == expected_inventory_val
    assert bs_data["assets"]["total_assets"] == round(-75.0 + 43.0 + expected_inventory_val, 2)

    # 4. payables = sum(PurchaseInvoice.total_amount) where status != "Paid" and invoice_type != "debit_note"
    #    We have one Pending purchase invoice of 240.0.
    #    payables = 240.0.
    assert bs_data["liabilities"]["payables"] == 240.0
    assert bs_data["liabilities"]["total_liabilities"] == 240.0

    # 5. net_worth = total_assets - total_liabilities
    expected_net_worth = round((-75.0 + 43.0 + expected_inventory_val) - 240.0, 2)
    assert bs_data["net_worth"] == expected_net_worth


def test_accounting_tenant_isolation(api_auth):
    headers_a = api_auth["owner_a"]
    headers_b = api_auth["owner_b"]

    # Biz B should have 0/empty even though Biz A has data
    resp_b_db = client.get("/reports/day-book", headers=headers_b)
    assert resp_b_db.status_code == 200
    assert resp_b_db.json()["transactions"] == []

    resp_b_bs = client.get("/reports/balance-sheet", headers=headers_b)
    assert resp_b_bs.status_code == 200
    assert resp_b_bs.json()["assets"]["total_assets"] == 0.0
