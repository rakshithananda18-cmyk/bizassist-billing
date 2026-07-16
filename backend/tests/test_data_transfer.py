import os
import sys
import uuid

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_bizassist.db")
os.environ.setdefault("GROQ_API_KEY", "mock_groq_api_key")

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, backend_path)

from fastapi.testclient import TestClient
from main_groq import app
from database.db import SessionLocal
from database.models import Customer, Product, Invoice, InvoiceLineItem

client = TestClient(app)

def _signup(business_name):
    uname = f"own_{uuid.uuid4().hex[:8]}"
    r = client.post("/signup", json={
        "username": uname, "password": "TestPass123!", "business_name": business_name,
    })
    assert r.status_code == 200, r.text
    b = r.json()
    return {"headers": {"Authorization": f"Bearer {b['token']}"}, "bid": b["id"]}

def test_migration_lifecycle():
    # 1. Sign up a test business
    owner = _signup("Migration Test Shop")
    
    # 2. Add some dummy data directly via DB (Customer and Product)
    db = SessionLocal()
    try:
        cust = Customer(business_id=owner["bid"], name="Alice Test", phone="1234567890")
        prod = Product(business_id=owner["bid"], name="Alice Widget", selling_price=10.0, track_inventory=True)
        db.add(cust)
        db.add(prod)
        db.commit()
    finally:
        db.close()

    # 3. Call count endpoint
    r_count = client.get("/api/data-transfer/count", headers=owner["headers"])
    assert r_count.status_code == 200, r_count.text
    counts = r_count.json()
    assert counts.get("customers") == 1
    assert counts.get("products") == 1

    # 4. Call export endpoint
    r_export = client.get("/api/data-transfer/export", headers=owner["headers"])
    assert r_export.status_code == 200, r_export.text
    export_data = r_export.json()
    assert "tables" in export_data
    tables = export_data["tables"]
    assert len(tables.get("customers", [])) == 1
    assert len(tables.get("products", [])) == 1
    assert tables["customers"][0]["name"] == "Alice Test"

    # 5. Sign up another clean business
    owner_clean = _signup("Clean Migration Destination")

    # 6. Call count on clean business before import (should be 0)
    r_count_clean = client.get("/api/data-transfer/count", headers=owner_clean["headers"])
    assert r_count_clean.status_code == 200
    counts_clean = r_count_clean.json()
    assert counts_clean.get("customers", 0) == 0
    assert counts_clean.get("products", 0) == 0

    # 7. Modify the export data to map to clean owner's business_id
    imported_tables = {}
    for table_name, rows in tables.items():
        clean_rows = []
        for r in rows:
            new_row = dict(r)
            if "business_id" in new_row:
                new_row["business_id"] = owner_clean["bid"]
            # users table special mapping if present
            if table_name == "users":
                new_row["id"] = owner_clean["bid"]
            clean_rows.append(new_row)
        imported_tables[table_name] = clean_rows

    # 8. Post to import endpoint on clean business
    r_import = client.post("/api/data-transfer/import", headers=owner_clean["headers"], json={"tables": imported_tables})
    assert r_import.status_code == 200, r_import.text
    import_res = r_import.json()
    assert import_res["total"] > 0

    # 9. Verify counts are updated on the clean business
    r_count_after = client.get("/api/data-transfer/count", headers=owner_clean["headers"])
    assert r_count_after.status_code == 200
    counts_after = r_count_after.json()
    assert counts_after.get("customers") == 1
    assert counts_after.get("products") == 1


def test_migration_includes_invoice_line_items():
    """Regression (July 2026, 'invoices arrive with empty products'): line-item
    tables have no business_id column and used to export as [] — every
    cloud→local / device migration silently dropped invoice items. They must
    now be scoped through their parent document."""
    owner = _signup("Line Item Source Shop")

    db = SessionLocal()
    try:
        inv = Invoice(business_id=owner["bid"], invoice_id="LCL-OW-0001",
                      customer="Walk-in", amount=120.0, status="paid",
                      invoice_date="2026-07-16")
        db.add(inv)
        db.flush()
        db.add(InvoiceLineItem(invoice_id=inv.id, product_name="Brownie Slab",
                               quantity=2.0, unit_price=60.0))
        db.commit()
        inv_pk = inv.id
    finally:
        db.close()

    # Export must contain the line item, scoped through its parent invoice.
    r_export = client.get("/api/data-transfer/export", headers=owner["headers"])
    assert r_export.status_code == 200, r_export.text
    tables = r_export.json()["tables"]
    assert len(tables.get("invoices", [])) == 1
    lines = tables.get("invoice_line_items", [])
    assert len(lines) == 1, "invoice_line_items missing from export"
    assert lines[0]["product_name"] == "Brownie Slab"
    assert lines[0]["invoice_id"] == inv_pk

    # Count endpoint agrees.
    r_count = client.get("/api/data-transfer/count", headers=owner["headers"])
    assert r_count.status_code == 200
    assert r_count.json().get("invoice_line_items") == 1

    # Import into a clean business → the invoice arrives WITH its items.
    owner_clean = _signup("Line Item Destination Shop")
    imported_tables = {}
    for table_name, rows in tables.items():
        clean_rows = []
        for r in rows:
            new_row = dict(r)
            if "business_id" in new_row:
                new_row["business_id"] = owner_clean["bid"]
            if table_name == "users":
                new_row["id"] = owner_clean["bid"]
            clean_rows.append(new_row)
        imported_tables[table_name] = clean_rows

    r_import = client.post("/api/data-transfer/import",
                           headers=owner_clean["headers"],
                           json={"tables": imported_tables})
    assert r_import.status_code == 200, r_import.text

    db = SessionLocal()
    try:
        dest_inv = (db.query(Invoice)
                      .filter(Invoice.business_id == owner_clean["bid"],
                              Invoice.invoice_id == "LCL-OW-0001")
                      .first())
        assert dest_inv is not None
        items = (db.query(InvoiceLineItem)
                   .filter(InvoiceLineItem.invoice_id == dest_inv.id)
                   .all())
        assert len(items) == 1, "imported invoice has no line items"
        assert items[0].product_name == "Brownie Slab"
    finally:
        db.close()
