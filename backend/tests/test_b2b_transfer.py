"""
tests/test_b2b_transfer.py
==========================
Bug fix: B2B relationship tables (connections / orders / order lines) were
dropped by every export/import because they're two-sided (buyer+seller user
ids) and the generic pipeline scopes by `business_id`. Verifies:
  • export includes the three tables with portable BizID identity keys
  • import restores them into a DB where the integer ids differ, resolving
    both parties by BizID and the seller invoice by its natural number
  • rows whose counterparty BizID is absent are skipped, never fatal
  • import is idempotent (second run creates no duplicates)
"""
import os
import sys
import uuid

os.environ["DATABASE_URL"] = "sqlite:///./test_bizassist.db"
os.environ["GROQ_API_KEY"] = "mock_groq_api_key"

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, backend_path)

import pytest
from fastapi.testclient import TestClient
from main_groq import app
from database.db import SessionLocal
from database.models import User, Product
from core.models import B2BConnection, B2BOrder, B2BOrderLineItem

client = TestClient(app)


def _signup(prefix):
    username = f"{prefix}_{uuid.uuid4().hex[:8]}"
    r = client.post("/signup", json={"username": username, "password": "TestPass123!",
                                     "business_name": f"{prefix} Biz"})
    assert r.status_code == 200, r.text
    b = r.json()
    return {"headers": {"Authorization": f"Bearer {b['token']}"}, "bid": b["id"]}


@pytest.fixture(scope="module")
def net():
    """Seller + buyer businesses with a connection, an order and two lines."""
    seller, buyer = _signup("test_bt_seller"), _signup("test_bt_buyer")
    db = SessionLocal()
    try:
        s = db.query(User).filter(User.id == seller["bid"]).first()
        b = db.query(User).filter(User.id == buyer["bid"]).first()
        # BizIDs must exist for identity re-resolution (signup normally sets them)
        if not s.public_id:
            s.public_id = f"BA-{uuid.uuid4().hex[:6].upper()}"
        if not b.public_id:
            b.public_id = f"BA-{uuid.uuid4().hex[:6].upper()}"
        p = Product(business_id=seller["bid"], name="Basmati 5kg", unit="Bag",
                    selling_price=450, track_inventory=False)
        db.add(p)
        db.flush()
        conn = B2BConnection(seller_business_id=s.id, buyer_business_id=b.id,
                             price_tier="wholesale", discount_pct=5.0, status="accepted")
        order = B2BOrder(buyer_business_id=b.id, seller_business_id=s.id,
                         order_number=f"B2B-ORD-TEST-{uuid.uuid4().hex[:4].upper()}",
                         order_date="2026-06-30", status="completed",
                         subtotal=900.0, total_amount=945.0)
        db.add_all([conn, order])
        db.flush()
        db.add_all([
            B2BOrderLineItem(order_id=order.id, product_id=p.id, product_name="Basmati 5kg",
                             quantity=2, unit_price=450, line_total=900),
            B2BOrderLineItem(order_id=order.id, product_id=p.id, product_name="Basmati 5kg",
                             quantity=1, unit_price=45, line_total=45),
        ])
        db.commit()
        info = {"seller": seller, "buyer": buyer, "order_number": order.order_number,
                "seller_bizid": s.public_id, "buyer_bizid": b.public_id}
    finally:
        db.close()
    return info


def test_export_includes_b2b_tables_with_bizids(net):
    r = client.get("/api/data-transfer/export", headers=net["seller"]["headers"])
    assert r.status_code == 200, r.text
    tables = r.json()["tables"]

    assert "b2b_connections" in tables, "connections missing from export"
    assert "b2b_orders" in tables, "orders missing from export"
    assert "b2b_order_line_items" in tables, "order lines missing from export"

    conn = tables["b2b_connections"][0]
    assert conn["seller_bizid"] == net["seller_bizid"]
    assert conn["buyer_bizid"] == net["buyer_bizid"]

    order = next(o for o in tables["b2b_orders"] if o["order_number"] == net["order_number"])
    assert order["seller_bizid"] and order["buyer_bizid"]

    lines = [l for l in tables["b2b_order_line_items"]
             if l["order_number_ref"] == net["order_number"]]
    assert len(lines) == 2
    assert lines[0]["product_uid"]


def test_import_restores_b2b_data_and_is_idempotent(net):
    export = client.get("/api/data-transfer/export", headers=net["seller"]["headers"]).json()

    # Wipe the B2B rows — the "fresh destination DB" scenario.
    db = SessionLocal()
    try:
        db.query(B2BOrderLineItem).delete()
        db.query(B2BOrder).filter(B2BOrder.order_number == net["order_number"]).delete()
        db.query(B2BConnection).filter(
            B2BConnection.seller_business_id == net["seller"]["bid"]).delete()
        db.commit()
    finally:
        db.close()

    payload = {"tables": {t: export["tables"][t] for t in
                          ("b2b_connections", "b2b_orders", "b2b_order_line_items")
                          if t in export["tables"]}}
    r = client.post("/api/data-transfer/import", headers=net["seller"]["headers"], json=payload)
    assert r.status_code == 200, r.text
    imported = r.json()["imported"]
    assert imported.get("b2b_connections") == 1
    assert imported.get("b2b_orders", 0) >= 1
    assert imported.get("b2b_order_line_items") == 2

    db = SessionLocal()
    try:
        conn = (db.query(B2BConnection)
                .filter(B2BConnection.seller_business_id == net["seller"]["bid"],
                        B2BConnection.buyer_business_id == net["buyer"]["bid"]).first())
        assert conn is not None and conn.price_tier == "wholesale"
        order = db.query(B2BOrder).filter(B2BOrder.order_number == net["order_number"]).first()
        assert order is not None and order.status == "completed"
        assert order.seller_business_id == net["seller"]["bid"]   # resolved via BizID
        assert len(order.line_items) == 2
    finally:
        db.close()

    # Second import → no duplicates (idempotent)
    r2 = client.post("/api/data-transfer/import", headers=net["seller"]["headers"], json=payload)
    assert r2.status_code == 200
    db = SessionLocal()
    try:
        order = db.query(B2BOrder).filter(B2BOrder.order_number == net["order_number"]).first()
        assert len(order.line_items) == 2
        n_conns = (db.query(B2BConnection)
                   .filter(B2BConnection.seller_business_id == net["seller"]["bid"]).count())
        assert n_conns == 1
    finally:
        db.close()

    # The API the B2B pages actually call now shows the restored data
    r = client.get("/connections/orders", params={"role": "seller"},
                   headers=net["seller"]["headers"])
    assert r.status_code == 200
    assert any(o["order_number"] == net["order_number"] for o in r.json())


def test_import_creates_counterparty_stub(net):
    """Cloud→Local reality: accounts are never synced, so an unknown
    counterparty BizID gets a minimal stub (real BizID + display name,
    unknowable password) so the relationship rows stay valid and visible."""
    export = client.get("/api/data-transfer/export", headers=net["seller"]["headers"]).json()
    rows = [dict(r) for r in export["tables"]["b2b_connections"]]
    for r_ in rows:
        r_["buyer_bizid"] = "BA-GHOST9"           # counterparty not in this DB
        r_["buyer_name"] = "Ghost Traders"
    r = client.post("/api/data-transfer/import", headers=net["seller"]["headers"],
                    json={"tables": {"b2b_connections": rows}})
    assert r.status_code == 200
    assert r.json()["imported"].get("b2b_connections") == 1

    db = SessionLocal()
    try:
        stub = db.query(User).filter(User.public_id == "BA-GHOST9").first()
        assert stub is not None
        assert stub.business_name == "Ghost Traders"
        assert stub.username.startswith("bizstub-")
        conn = (db.query(B2BConnection)
                .filter(B2BConnection.seller_business_id == net["seller"]["bid"],
                        B2BConnection.buyer_business_id == stub.id).first())
        assert conn is not None
    finally:
        db.close()


def test_import_without_bizid_skips_gracefully(net):
    """A row with NO identity key at all can't be resolved → skipped, never fatal."""
    export = client.get("/api/data-transfer/export", headers=net["seller"]["headers"]).json()
    rows = [dict(r) for r in export["tables"]["b2b_connections"]]
    for r_ in rows:
        r_["buyer_bizid"] = None
    r = client.post("/api/data-transfer/import", headers=net["seller"]["headers"],
                    json={"tables": {"b2b_connections": rows}})
    assert r.status_code == 200
    assert r.json()["imported"].get("b2b_connections") is None
