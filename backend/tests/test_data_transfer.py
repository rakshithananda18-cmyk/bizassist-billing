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
from database.models import Customer, Product

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
