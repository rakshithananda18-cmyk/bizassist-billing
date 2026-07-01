"""
tests/test_uid_sync_keys.py
===========================
Step 3 / R-3 Phase A — durable `uid` sync keys.

Locks down the Phase A contract (additive, no behaviour change):
  - every business-owned table has a `uid` column
  - new rows get a non-null, distinct uid auto-populated ORM-side
  - the backfill strategy fills NULL uids (mirrors the Alembic migration)

Match-on-uid behaviour itself is Phase B — not tested here.
"""
import os
import sys
import uuid
from datetime import datetime, timedelta

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_bizassist.db")
os.environ.setdefault("GROQ_API_KEY", "mock_groq_api_key")

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, backend_path)

from sqlalchemy import text, inspect
from fastapi.testclient import TestClient

# Importing the app builds the schema (Base.metadata.create_all) on the test DB.
from main_groq import app  # noqa: F401  (side effect: create_all)
from database.db import SessionLocal, engine
from database.models import Customer, Invoice, InvoiceLineItem

client = TestClient(app)

# The tables that carry `uid` (all 24 synced tables).
_UID_TABLES = [
    "customers", "vendors", "products", "invoices", "inventory", "payments",
    "purchase_orders", "purchase_invoices", "expenses", "godowns", "stock_transfers",
    "journal_entries", "period_locks",
    "invoice_line_items", "purchase_order_line_items", "purchase_invoice_line_items",
    "rate_limit_configs", "alert_configs", "stock_ledger", "product_barcodes",
    "business_settings", "invoice_payments", "b2b_ledgers", "stock_transfer_line_items",
]


def test_uid_column_present_on_all_owned_tables():
    insp = inspect(engine)
    existing = set(insp.get_table_names())
    for table in _UID_TABLES:
        assert table in existing, f"{table} missing from schema"
        cols = {c["name"] for c in insp.get_columns(table)}
        assert "uid" in cols, f"{table} is missing the uid column"


def test_new_rows_get_distinct_non_null_uid():
    db = SessionLocal()
    try:
        c1 = Customer(name=f"uidtest_{uuid.uuid4().hex[:6]}", business_id=1)
        c2 = Customer(name=f"uidtest_{uuid.uuid4().hex[:6]}", business_id=1)
        db.add_all([c1, c2])
        db.commit()
        db.refresh(c1)
        db.refresh(c2)

        assert c1.uid and c2.uid, "uid should be auto-populated on insert"
        assert len(c1.uid) == 36 and len(c2.uid) == 36, "uid should be a 36-char UUID"
        assert c1.uid != c2.uid, "uids must be distinct"
    finally:
        db.rollback()
        db.close()


def test_backfill_fills_null_uid():
    """A row whose uid was nulled (pre-migration state) gets filled — same UPDATE
    the SQLite branch of the migration runs."""
    db = SessionLocal()
    try:
        c = Customer(name=f"backfill_{uuid.uuid4().hex[:6]}", business_id=1)
        db.add(c)
        db.commit()
        cid = c.id

        # Simulate a legacy row with no uid.
        db.execute(text('UPDATE customers SET uid = NULL WHERE id = :i'), {"i": cid})
        db.commit()
        assert db.execute(
            text('SELECT uid FROM customers WHERE id = :i'), {"i": cid}
        ).scalar() is None

        # Backfill (mirrors migration SQLite branch).
        rows = db.execute(text('SELECT id FROM customers WHERE uid IS NULL')).fetchall()
        for (row_id,) in rows:
            db.execute(
                text('UPDATE customers SET uid = :u WHERE id = :i'),
                {"u": str(uuid.uuid4()), "i": row_id},
            )
        db.commit()

        filled = db.execute(
            text('SELECT uid FROM customers WHERE id = :i'), {"i": cid}
        ).scalar()
        assert filled and len(filled) == 36, "backfill must populate a uid"
    finally:
        db.rollback()
        db.close()


def test_sync_cross_db_no_collision():
    uname = f"own_{uuid.uuid4().hex[:8]}"
    r = client.post("/signup", json={
        "username": uname, "password": "TestPass123!", "business_name": "No Collision Shop",
    })
    assert r.status_code == 200
    b = r.json()
    headers = {"Authorization": f"Bearer {b['token']}"}
    bid = b["id"]

    db = SessionLocal()
    try:
        db.execute(text("DELETE FROM customers WHERE id = 9999 OR uid IN ('uid-local-unique-123', 'uid-remote-unique-456')"))
        db.commit()
        local_cust = Customer(
            id=9999,
            business_id=bid,
            uid="uid-local-unique-123",
            name="Local Cust",
            updated_at=datetime.utcnow()
        )
        db.add(local_cust)
        db.commit()
    finally:
        db.close()

    push_body = {
        "changes": [{
            "entity": "customers",
            "entity_id": 9999,
            "operation": "INSERT",
            "payload": {
                "id": 9999,
                "business_id": bid,
                "uid": "uid-remote-unique-456",
                "name": "Remote Cust",
                "updated_at": datetime.utcnow().isoformat()
            },
            "created_at": datetime.utcnow().isoformat()
        }]
    }
    resp = client.post("/api/sync/push", headers=headers, json=push_body)
    assert resp.status_code == 200, resp.text
    assert resp.json()["applied"] == 1

    db = SessionLocal()
    try:
        c_local = db.query(Customer).filter(Customer.uid == "uid-local-unique-123").first()
        c_remote = db.query(Customer).filter(Customer.uid == "uid-remote-unique-456").first()
        assert c_local is not None
        assert c_remote is not None
        assert c_local.name == "Local Cust"
        assert c_remote.name == "Remote Cust"
        assert c_local.id != c_remote.id
    finally:
        db.close()


def test_sync_child_fk_by_parent_uid():
    db = SessionLocal()
    try:
        db.execute(text("DELETE FROM invoice_line_items WHERE id = 8888"))
        db.execute(text("DELETE FROM invoices WHERE id = 9999"))
        db.commit()
    finally:
        db.close()

    uname = f"own_{uuid.uuid4().hex[:8]}"
    r = client.post("/signup", json={
        "username": uname, "password": "TestPass123!", "business_name": "FK Shop",
    })
    assert r.status_code == 200
    b = r.json()
    headers = {"Authorization": f"Bearer {b['token']}"}
    bid = b["id"]

    parent_uid = f"parent-inv-{uuid.uuid4().hex[:6]}"
    child_uid = f"child-item-{uuid.uuid4().hex[:6]}"

    push_body = {
        "changes": [
            {
                "entity": "invoices",
                "entity_id": 9999,
                "operation": "INSERT",
                "payload": {
                    "id": 9999,
                    "business_id": bid,
                    "uid": parent_uid,
                    "invoice_number": "INV-TEST-100",
                    "total_amount": 100.0,
                    "updated_at": datetime.utcnow().isoformat()
                },
                "created_at": datetime.utcnow().isoformat()
            },
            {
                "entity": "invoice_line_items",
                "entity_id": 8888,
                "operation": "INSERT",
                "payload": {
                    "id": 8888,
                    "uid": child_uid,
                    "invoice_id": 9999,
                    "invoice_id_uid": parent_uid,
                    "product_name": "Item A",
                    "quantity": 1.0,
                    "unit_price": 100.0,
                    "updated_at": datetime.utcnow().isoformat()
                },
                "created_at": datetime.utcnow().isoformat()
            }
        ]
    }

    resp = client.post("/api/sync/push", headers=headers, json=push_body)
    assert resp.status_code == 200, resp.text
    assert resp.json()["applied"] == 2

    db = SessionLocal()
    try:
        inv = db.query(Invoice).filter(Invoice.uid == parent_uid).first()
        item = db.query(InvoiceLineItem).filter(InvoiceLineItem.uid == child_uid).first()
        
        assert inv is not None
        assert item is not None
        assert item.invoice_id == inv.id
        assert item.product_name == "Item A"
    finally:
        db.close()


def test_sync_merge_lww_uid():
    uname = f"own_{uuid.uuid4().hex[:8]}"
    r = client.post("/signup", json={
        "username": uname, "password": "TestPass123!", "business_name": "LWW Shop",
    })
    assert r.status_code == 200
    b = r.json()
    headers = {"Authorization": f"Bearer {b['token']}"}
    bid = b["id"]

    cust_uid = f"lww-cust-{uuid.uuid4().hex[:6]}"
    t1 = datetime.utcnow()
    t2 = t1 + timedelta(minutes=10)
    t0 = t1 - timedelta(minutes=10)

    client.post("/api/sync/push", headers=headers, json={
        "changes": [{
            "entity": "customers",
            "entity_id": 1,
            "operation": "INSERT",
            "payload": {
                "id": 1,
                "business_id": bid,
                "uid": cust_uid,
                "name": "Bob Original",
                "updated_at": t1.isoformat()
            },
            "created_at": t1.isoformat()
        }]
    })

    resp2 = client.post("/api/sync/push", headers=headers, json={
        "changes": [{
            "entity": "customers",
            "entity_id": 1,
            "operation": "UPDATE",
            "payload": {
                "id": 1,
                "business_id": bid,
                "uid": cust_uid,
                "name": "Bob Newer",
                "updated_at": t2.isoformat()
            },
            "created_at": t2.isoformat()
        }]
    })
    assert resp2.status_code == 200, resp2.text
    assert resp2.json()["applied"] == 1

    resp3 = client.post("/api/sync/push", headers=headers, json={
        "changes": [{
            "entity": "customers",
            "entity_id": 1,
            "operation": "UPDATE",
            "payload": {
                "id": 1,
                "business_id": bid,
                "uid": cust_uid,
                "name": "Bob Older",
                "updated_at": t0.isoformat()
            },
            "created_at": t0.isoformat()
        }]
    })
    assert resp3.status_code == 200, resp3.text
    assert resp3.json()["applied"] == 0

    db = SessionLocal()
    try:
        cust = db.query(Customer).filter(Customer.uid == cust_uid).first()
        assert cust is not None
        assert cust.name == "Bob Newer"
    finally:
        db.close()


def test_sync_id_fallback():
    uname = f"own_{uuid.uuid4().hex[:8]}"
    r = client.post("/signup", json={
        "username": uname, "password": "TestPass123!", "business_name": "Fallback Shop",
    })
    assert r.status_code == 200
    b = r.json()
    headers = {"Authorization": f"Bearer {b['token']}"}
    bid = b["id"]

    db = SessionLocal()
    try:
        cust = Customer(
            business_id=bid,
            name="Bob Legacy",
            updated_at=datetime.utcnow()
        )
        db.add(cust)
        db.commit()
        cust_id = cust.id
    finally:
        db.close()

    push_body = {
        "changes": [{
            "entity": "customers",
            "entity_id": cust_id,
            "operation": "UPDATE",
            "payload": {
                "id": cust_id,
                "business_id": bid,
                "name": "Bob Legacy Updated",
                "updated_at": (datetime.utcnow() + timedelta(minutes=5)).isoformat()
            },
            "created_at": datetime.utcnow().isoformat()
        }]
    }

    resp = client.post("/api/sync/push", headers=headers, json=push_body)
    assert resp.status_code == 200, resp.text
    assert resp.json()["applied"] == 1

    db = SessionLocal()
    try:
        cust = db.query(Customer).filter(Customer.id == cust_id).first()
        assert cust is not None
        assert cust.name == "Bob Legacy Updated"
    finally:
        db.close()

