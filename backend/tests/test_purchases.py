import os
import sys
import uuid
from unittest.mock import patch

os.environ["DATABASE_URL"] = "sqlite:///./test_bizassist.db"
os.environ["GROQ_API_KEY"] = "mock_groq_api_key"

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, backend_path)

import pytest
from fastapi.testclient import TestClient
from main_groq import app
from database.db import SessionLocal
from database.models import Base, Product, PurchaseInvoice, PurchaseInvoiceLineItem, Inventory, User, Vendor
from core.models import StockLedger, ProductBarcode
from core.stock import ledger as SL
from services.purchase_mapper import map_purchase_items_to_catalog
from core.purchase.commands import accept_supplier_invoice

client = TestClient(app)
BID = 800800


def _ensure_schema():
    db = SessionLocal()
    try:
        Base.metadata.create_all(bind=db.get_bind())
    finally:
        db.close()


def _clear():
    db = SessionLocal()
    try:
        # Delete purchase entities
        ids = [r.id for r in db.query(PurchaseInvoice.id).filter(PurchaseInvoice.business_id == BID).all()]
        if ids:
            db.query(PurchaseInvoiceLineItem).filter(PurchaseInvoiceLineItem.purchase_invoice_id.in_(ids)).delete(synchronize_session=False)
        db.query(PurchaseInvoice).filter(PurchaseInvoice.business_id == BID).delete()
        db.query(StockLedger).filter(StockLedger.business_id == BID).delete()
        db.query(ProductBarcode).filter(ProductBarcode.business_id == BID).delete()
        db.query(Inventory).filter(Inventory.business_id == BID).delete()
        db.query(Product).filter(Product.business_id == BID).delete()
        db.query(Vendor).filter(Vendor.business_id == BID).delete()
        db.query(User).filter(User.id == BID).delete()
        db.commit()
    finally:
        db.close()


@pytest.fixture(autouse=True)
def _setup():
    _ensure_schema()
    _clear()
    db = SessionLocal()
    try:
        db.add(User(id=BID, username=f"biz{BID}", password="x", role="enterprise"))
        db.commit()
    finally:
        db.close()
    yield
    _clear()


# ── Fuzzy Matching Tests ─────────────────────────────────────────────────────

def test_fuzzy_matching():
    db = SessionLocal()
    try:
        # Seed catalog
        p1 = Product(business_id=BID, name="Paracetamol 650mg", cost_price=10.0, track_inventory=True)
        p2 = Product(business_id=BID, name="Amoxicillin 500mg", cost_price=20.0, track_inventory=True)
        db.add_all([p1, p2])
        db.commit()
        
        extracted = [
            {"product_name": "Parasetamol 650", "quantity": 5, "unit_price": 12.0},
            {"product_name": "Unrelated Product Name", "quantity": 1, "unit_price": 50.0}
        ]
        
        mapped = map_purchase_items_to_catalog(db, BID, extracted)
        
        # Paracetamol should fuzzy match Paracetamol 650mg
        assert mapped[0]["product_id"] == p1.id
        assert mapped[0]["is_matched"] is True
        assert mapped[0]["confidence_score"] > 0.8
        
        # Unrelated should not match high confidence
        assert mapped[1]["is_matched"] is False
    finally:
        db.close()


# ── Accept Supplier Invoice Command Tests ────────────────────────────────────

def test_accept_supplier_invoice():
    db = SessionLocal()
    try:
        # Seed catalog product
        p = Product(business_id=BID, name="Dolo 650", cost_price=15.0, unit="Nos", track_inventory=True)
        db.add(p)
        db.flush()
        
        # Seed inventory cache
        inv = Inventory(business_id=BID, product_id=p.id, product_name=p.name, stock=5)
        db.add(inv)
        SL.record_movement(db, business_id=BID, movement_type=SL.OPENING,
                           qty_delta=5.0, product_id=p.id, product_name=p.name, update_cache=False)
        db.commit()
        
        invoice_payload = {
            "supplier_name": "Apex Pharma",
            "invoice_number": "PUR-99812",
            "invoice_date": "2026-06-15",
            "status": "Paid",
            "total_amount": 120.0,
            "items": [
                {
                    "product_id": p.id,
                    "product_name": "Dolo 650",
                    "quantity": 10.0,
                    "purchase_unit": "Nos",
                    "conversion_factor": 1.0,
                    "unit_price": 12.0,
                    "taxable_value": 120.0,
                    "line_total": 120.0
                }
            ]
        }
        
        # Execute command
        invoice = accept_supplier_invoice(db, BID, invoice_payload)
        
        # Verify invoice created
        assert invoice.id is not None
        assert invoice.invoice_number == "PUR-99812"
        assert invoice.supplier_name == "Apex Pharma"
        
        # Verify cost price updated
        db.refresh(p)
        assert p.cost_price == 12.0
        
        # Verify stock movement recorded
        movements = db.query(StockLedger).filter(
            StockLedger.business_id == BID,
            StockLedger.product_id == p.id,
            StockLedger.movement_type == SL.PURCHASE
        ).all()
        assert len(movements) == 1
        assert movements[0].qty_delta == 10.0
        
        # Verify inventory cache updated
        db.refresh(inv)
        assert inv.stock == 15 # 5 original + 10 purchased
        
        # Verify idempotency (should raise ValueError on duplicate)
        with pytest.raises(ValueError, match="already been processed"):
            accept_supplier_invoice(db, BID, invoice_payload)
            
    finally:
        db.close()


# ── API Scoping & Role Restrictions Tests ────────────────────────────────────

@pytest.fixture(scope="module")
def api_auth():
    # Setup owner business
    owner_username = f"owner_{uuid.uuid4().hex[:6]}"
    resp = client.post("/signup", json={
        "username": owner_username, "password": "OwnerPass123!", "business_name": "Owner Store",
    })
    assert resp.status_code == 200
    owner_data = resp.json()
    owner_token = owner_data["token"]
    owner_bid = owner_data["id"]
    
    # Setup cashier in same business
    cashier_username = f"cashier_{uuid.uuid4().hex[:6]}"
    # Create the user directly in the DB under same business ID
    db = SessionLocal()
    try:
        from services.auth import hash_password
        cashier = User(
            id=owner_bid + 9999, # unique user ID
            username=cashier_username,
            password=hash_password("CashierPass123!"),
            business_name="Owner Store",
            role="cashier"
        )
        db.add(cashier)
        db.commit()
    finally:
        db.close()
        
    # Get cashier token by logging in
    login_resp = client.post("/login", json={
        "username": cashier_username, "password": "CashierPass123!"
    })
    assert login_resp.status_code == 200
    cashier_token = login_resp.json()["token"]
    
    return {
        "owner_headers": {"Authorization": f"Bearer {owner_token}"},
        "cashier_headers": {"Authorization": f"Bearer {cashier_token}"},
        "bid": owner_bid
    }


def test_api_cashier_restricted(api_auth):
    # Owner can upload (mocking OCR extraction)
    with patch("core.api.purchases.parse_purchase_file") as mock_parse:
        mock_parse.return_value = {
            "supplier_name": "Apex Supply",
            "invoice_number": "INV-332",
            "invoice_date": "2026-06-15",
            "items": []
        }
        
        # Owner upload should succeed (200)
        owner_upload = client.post(
            "/purchases/upload", 
            headers=api_auth["owner_headers"],
            files={"file": ("bill.pdf", b"mock pdf bytes", "application/pdf")}
        )
        assert owner_upload.status_code == 200
        
        # Cashier upload should fail (403 Forbidden)
        cashier_upload = client.post(
            "/purchases/upload", 
            headers=api_auth["cashier_headers"],
            files={"file": ("bill.pdf", b"mock pdf bytes", "application/pdf")}
        )
        assert cashier_upload.status_code == 403
        
        # Cashier confirm should fail (403 Forbidden)
        cashier_confirm = client.post(
            "/purchases/confirm",
            headers=api_auth["cashier_headers"],
            json={"supplier_name": "Apex", "invoice_number": "INV-332", "items": []}
        )
        assert cashier_confirm.status_code == 403
        
        # Cashier list should fail (403 Forbidden)
        cashier_list = client.get(
            "/purchases",
            headers=api_auth["cashier_headers"]
        )
        assert cashier_list.status_code == 403


def test_accept_supplier_invoice_with_barcode():
    db = SessionLocal()
    try:
        # Seed catalog product
        p = Product(business_id=BID, name="Panadol 500mg", cost_price=10.0, unit="Nos", track_inventory=True)
        db.add(p)
        db.commit()

        invoice_payload = {
            "supplier_name": "Apex Pharma",
            "invoice_number": "PUR-BC-1234",
            "invoice_date": "2026-06-15",
            "status": "Paid",
            "total_amount": 100.0,
            "items": [
                {
                    "product_id": p.id,
                    "product_name": "Panadol 500mg",
                    "quantity": 10.0,
                    "purchase_unit": "Nos",
                    "conversion_factor": 1.0,
                    "unit_price": 10.0,
                    "taxable_value": 100.0,
                    "line_total": 100.0,
                    "barcode": "1234567890123"
                }
            ]
        }

        # Confirm supplier invoice
        invoice = accept_supplier_invoice(db, BID, invoice_payload)
        assert invoice.id is not None

        # Verify barcode added to catalog
        from core.catalog.barcode import resolve_barcode
        matched_product = resolve_barcode(db, BID, "1234567890123")
        assert matched_product is not None
        assert matched_product.id == p.id
    finally:
        db.close()


def test_create_debit_note():
    db = SessionLocal()
    try:
        # 1. Seed product
        p = Product(business_id=BID, name="Panadol 500mg", cost_price=10.0, unit="Nos", track_inventory=True)
        db.add(p)
        db.commit()

        # 2. Seed inventory cache
        inv = Inventory(business_id=BID, product_id=p.id, product_name=p.name, stock=20)
        db.add(inv)
        db.commit()

        # 3. Create purchase invoice
        invoice_payload = {
            "supplier_name": "Apex Pharma",
            "invoice_number": "PUR-DN-1234",
            "invoice_date": "2026-06-15",
            "status": "Paid",
            "total_amount": 200.0,
            "items": [
                {
                    "product_id": p.id,
                    "product_name": "Panadol 500mg",
                    "quantity": 20.0,
                    "purchase_unit": "Nos",
                    "conversion_factor": 1.0,
                    "unit_price": 10.0,
                    "taxable_value": 200.0,
                    "line_total": 200.0
                }
            ]
        }
        invoice = accept_supplier_invoice(db, BID, invoice_payload)
        assert invoice.id is not None

        # 4. Create debit note returning 5 items
        from core.purchase.commands import create_debit_note
        dn_lines = [
            {
                "product_id": p.id,
                "quantity": 5.0,
                "reason": "Damaged goods"
            }
        ]
        debit_note = create_debit_note(
            db=db,
            business_id=BID,
            original_purchase_id=invoice.id,
            lines=dn_lines,
            note="Test debit note note",
            debit_note_no="DN-TEST-99"
        )

        assert debit_note.id is not None
        assert debit_note.invoice_type == "debit_note"
        assert debit_note.invoice_number == "DN-TEST-99"
        assert debit_note.total_amount == 50.0 # 5 * 10.0

        # Verify stock movement: -5.0 quantity (reduction)
        movements = db.query(StockLedger).filter(
            StockLedger.business_id == BID,
            StockLedger.product_id == p.id,
            StockLedger.movement_type == SL.RETURN_OUT
        ).all()
        assert len(movements) == 1
        assert movements[0].qty_delta == -5.0
        assert movements[0].reference_id == debit_note.id
    finally:
        db.close()


def test_expenses_and_debit_notes_api(api_auth):
    # 1. Test logging an expense via API
    expense_payload = {
        "expense_date": "2026-06-17",
        "category": "Rent",
        "expense_type": "Indirect",
        "amount": 1500.0,
        "payment_mode": "Bank",
        "note": "Office rent payment"
    }
    create_exp_resp = client.post(
        "/expenses",
        headers=api_auth["owner_headers"],
        json=expense_payload
    )
    assert create_exp_resp.status_code == 201
    expense_data = create_exp_resp.json()
    assert expense_data["id"] is not None
    assert expense_data["amount"] == 1500.0
    assert expense_data["category"] == "Rent"

    # 2. Test listing expenses
    list_exp_resp = client.get(
        "/expenses",
        headers=api_auth["owner_headers"]
    )
    assert list_exp_resp.status_code == 200
    expenses_list = list_exp_resp.json()
    assert len(expenses_list) >= 1
    assert any(e["id"] == expense_data["id"] for e in expenses_list)

    # 3. Test P&L report returns the correct expenses
    pnl_resp_before = client.get(
        "/reports/profit-loss",
        headers=api_auth["owner_headers"]
    )
    assert pnl_resp_before.status_code == 200
    metrics_before = {m["metric"]: m["amount"] for m in pnl_resp_before.json()}
    assert metrics_before.get("Indirect Expenses (OPEX)") == 1500.0
    assert metrics_before.get("Total Expenses (OPEX)") == 1500.0

    # 4. Test deleting expense
    del_resp = client.delete(
        f"/expenses/{expense_data['id']}",
        headers=api_auth["owner_headers"]
    )
    assert del_resp.status_code == 200
    assert del_resp.json()["success"] is True

    # 5. Verify expense is deleted in P&L
    pnl_resp_after = client.get(
        "/reports/profit-loss",
        headers=api_auth["owner_headers"]
    )
    metrics_after = {m["metric"]: m["amount"] for m in pnl_resp_after.json()}
    assert metrics_after.get("Indirect Expenses (OPEX)") == 0.0
    assert metrics_after.get("Total Expenses (OPEX)") == 0.0

    # 6. Test Debit Notes via API
    # 6a. First we need a product
    db = SessionLocal()
    try:
        p = Product(business_id=api_auth["bid"], name="API Tablet", cost_price=25.0, unit="Nos", track_inventory=True)
        db.add(p)
        db.commit()
        db.refresh(p)
        prod_id = p.id
    finally:
        db.close()

    # 6b. Confirm a purchase invoice
    purchase_payload = {
        "supplier_name": "Apex API Dist",
        "invoice_number": "PUR-API-101",
        "invoice_date": "2026-06-15",
        "status": "Paid",
        "total_amount": 250.0,
        "items": [
            {
                "product_id": prod_id,
                "product_name": "API Tablet",
                "quantity": 10.0,
                "purchase_unit": "Nos",
                "conversion_factor": 1.0,
                "unit_price": 25.0,
                "taxable_value": 250.0,
                "line_total": 250.0
            }
        ]
    }
    conf_resp = client.post(
        "/purchases/confirm",
        headers=api_auth["owner_headers"],
        json=purchase_payload
    )
    assert conf_resp.status_code == 200
    purchase_id = conf_resp.json()["id"]

    # 6c. List purchases should show this invoice
    list_pur_resp = client.get(
        "/purchases",
        headers=api_auth["owner_headers"]
    )
    assert list_pur_resp.status_code == 200
    purchases_list = list_pur_resp.json()
    assert any(x["id"] == purchase_id for x in purchases_list)

    # 6d. Create debit note returning 2 tablets
    dn_payload = {
        "original_purchase_id": purchase_id,
        "debit_note_number": "DN-API-99",
        "lines": [
            {
                "product_id": prod_id,
                "quantity": 2.0,
                "reason": "Wrong batch"
            }
        ],
        "note": "Returned 2 tablets"
    }
    create_dn_resp = client.post(
        "/purchases/debit-notes",
        headers=api_auth["owner_headers"],
        json=dn_payload
    )
    assert create_dn_resp.status_code == 201
    dn_data = create_dn_resp.json()
    assert dn_data["id"] is not None
    assert dn_data["invoice_type"] == "debit_note"
    assert dn_data["total_amount"] == 50.0

    # 6e. List debit notes
    list_dn_resp = client.get(
        "/purchases/debit-notes",
        headers=api_auth["owner_headers"]
    )
    assert list_dn_resp.status_code == 200
    dn_list = list_dn_resp.json()
    assert any(x["id"] == dn_data["id"] for x in dn_list)

    # 6f. Check P&L report for purchases and purchase returns
    pnl_resp_final = client.get(
        "/reports/profit-loss",
        headers=api_auth["owner_headers"]
    )
    metrics_final = {m["metric"]: m["amount"] for m in pnl_resp_final.json()}
    # Net purchases should be 250 (original) - 50 (debit note) = 200
    assert metrics_final.get("Net Purchases (Inventory)") == 200.0



