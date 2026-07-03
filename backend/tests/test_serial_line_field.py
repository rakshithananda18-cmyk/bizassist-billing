"""
tests/test_serial_line_field.py
===============================
Serial/IMEI line field end-to-end (Sales structural chunk):
  POS "Save Bill" (POST /invoices) with serial_no on a line
    → persists on invoice_line_items.serial_no
    → surfaces in the print payload line + the `serial` visibility column.
"""
import os
import sys
import uuid

os.environ["DATABASE_URL"] = "sqlite:///./test_bizassist.db"
os.environ["GROQ_API_KEY"] = "mock_groq_api_key"

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, backend_path)

from fastapi.testclient import TestClient
from main_groq import app
from database.db import SessionLocal
from database.models import Product, Invoice

client = TestClient(app)


def test_serial_no_flows_from_pos_to_print_payload():
    username = f"test_serial_{uuid.uuid4().hex[:8]}"
    r = client.post("/signup", json={"username": username, "password": "TestPass123!",
                                     "business_name": "Mobile Shop"})
    assert r.status_code == 200, r.text
    headers = {"Authorization": f"Bearer {r.json()['token']}"}
    bid = r.json()["id"]

    db = SessionLocal()
    try:
        p = Product(business_id=bid, name="Redmi 13C", unit="Nos",
                    selling_price=8999, track_inventory=False,
                    cgst_rate=9, sgst_rate=9, igst_rate=18)
        db.add(p)
        db.commit()
        pid = p.id
    finally:
        db.close()

    # Shift gatekeeper (Phase 3): POST /invoices needs an OPEN register shift.
    r = client.post("/shifts/open", headers=headers, json={"opening_cash": 0})
    assert r.status_code == 201, r.text

    # POS "Save Bill" path (the outbox route) with a serial on the line
    r = client.post("/invoices", headers=headers, json={
        "items": [{"product_id": pid, "product": "Redmi 13C", "qty": 1,
                   "price": 8999, "cgst_rate": 9, "sgst_rate": 9,
                   "serial_no": "IMEI-358910111213"}],
        "gst_enabled": False,
        "paid_amount": 0.0,
    })
    assert r.status_code == 201, r.text
    invoice_no = r.json()["invoice_no"]

    # persisted on the line
    db = SessionLocal()
    try:
        inv = (db.query(Invoice)
               .filter(Invoice.business_id == bid, Invoice.invoice_id == invoice_no)
               .first())
        assert inv is not None
        assert inv.line_items[0].serial_no == "IMEI-358910111213"
    finally:
        db.close()

    # surfaces in the print payload (line value + visibility column)
    r = client.get(f"/sales/{invoice_no}/print-payload", headers=headers)
    assert r.status_code == 200, r.text
    pl = r.json()
    assert pl["lines"][0]["serial_no"] == "IMEI-358910111213"
    assert "serial" in pl["visibility"]["columns"]
