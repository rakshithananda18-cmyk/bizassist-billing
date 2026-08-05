"""
tests/test_outbox_reenrichment.py
=================================
`_repair_stuck_child_payloads` re-enriches pending outbox payloads that carry a
raw local FK and no portable `*_uid`. It used to work from a hardcoded map of
six CHILD tables with one parent each, and its query only selected those
entities — so a PARENT row's own foreign key was invisible to it twice over.

`invoices.customer_id` is exactly that. Ten invoices for business 126 sat in the
outbox with a raw customer id, the cloud could not resolve them, it dropped the
link (M-9 set_null) and tried to log the drop — and that log violated
`conflict_logs.entity_id NOT NULL`, aborting the whole push transaction every 15
seconds until the outbox was patched by hand.

Had this loop covered parent FKs, it would have self-healed on the next cycle.
"""
import json
import os
import sys
import uuid

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_bizassist.db")
os.environ.setdefault("GROQ_API_KEY", "mock_groq_api_key")

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, backend_path)

from fastapi.testclient import TestClient          # noqa: E402
from sqlalchemy import text                         # noqa: E402
from main_groq import app                           # noqa: E402
from database.db import SessionLocal                # noqa: E402
from database.models import Customer, Invoice       # noqa: E402
from services.sync_worker import _repair_stuck_child_payloads  # noqa: E402

client = TestClient(app)


def _hybrid_business():
    uname = f"rx_{uuid.uuid4().hex[:8]}"
    r = client.post("/signup", json={
        "username": uname, "password": "TestPass123!", "business_name": "Reenrich Co",
    })
    assert r.status_code == 200, r.text
    acct = r.json()
    bid = acct["user"]["id"] if isinstance(acct.get("user"), dict) else acct["id"]
    db = SessionLocal()
    db.execute(text("UPDATE users SET settings = :s WHERE id = :b"), {
        "s": json.dumps({"general": {"hosting_mode": "hybrid"}}), "b": bid,
    })
    db.commit()
    return db, bid


def test_a_parent_rows_own_fk_is_re_enriched():
    """The production shape: an invoice queued with customer_id and no uid,
    exactly as a raw-DB-API repair script leaves it (no mapper event fires, so
    no enrichment happens)."""
    db, bid = _hybrid_business()
    try:
        cust = Customer(business_id=bid, name="Brownie Factory")
        db.add(cust)
        db.commit()
        db.refresh(cust)
        assert cust.uid, "the parent must carry a uid for this to be resolvable"

        inv = Invoice(business_id=bid, invoice_id=f"INV-{uuid.uuid4().hex[:6]}",
                      customer="Brownie Factory", customer_id=cust.id, amount=100.0)
        db.add(inv)
        db.commit()

        # An unenriched outbox row, as the repair script produced.
        db.execute(text("DELETE FROM sync_queue WHERE business_id = :b"), {"b": bid})
        db.execute(text(
            "INSERT INTO sync_queue (business_id, entity, entity_id, operation, payload, created_at) "
            "VALUES (:b, 'invoices', :e, 'UPDATE', :p, datetime('now'))"
        ), {"b": bid, "e": inv.id,
            "p": json.dumps({"id": inv.id, "business_id": bid,
                             "customer_id": cust.id, "customer": "Brownie Factory"})})
        db.commit()

        assert _repair_stuck_child_payloads(db, bid) == 1

        row = db.execute(text(
            "SELECT payload FROM sync_queue WHERE business_id = :b"), {"b": bid}).fetchone()
        pay = json.loads(row[0])
        assert pay.get("customer_uid") == cust.uid, (
            "the invoice still has only a LOCAL customer id — the receiver has "
            f"nothing to resolve against: {sorted(pay)}"
        )
        assert pay.get("customer_id_uid") == cust.uid, "both key forms are probed"
        assert pay["customer_id"] == cust.id, "the raw value stays as the fallback"
    finally:
        db.close()


def test_nothing_to_do_is_a_no_op():
    """It runs on every push cycle, so an already-enriched outbox must cost
    nothing and report nothing."""
    db, bid = _hybrid_business()
    try:
        cust = Customer(business_id=bid, name="Already Fine")
        db.add(cust)
        db.commit()
        db.refresh(cust)

        db.execute(text("DELETE FROM sync_queue WHERE business_id = :b"), {"b": bid})
        db.execute(text(
            "INSERT INTO sync_queue (business_id, entity, entity_id, operation, payload, created_at) "
            "VALUES (:b, 'invoices', 1, 'UPDATE', :p, datetime('now'))"
        ), {"b": bid, "p": json.dumps({"id": 1, "business_id": bid,
                                       "customer_id": cust.id,
                                       "customer_uid": cust.uid})})
        db.commit()

        assert _repair_stuck_child_payloads(db, bid) == 0
    finally:
        db.close()
