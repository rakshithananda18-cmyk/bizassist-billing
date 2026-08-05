"""
tests/test_upload_delete_syncs.py
=================================
C-6: DELETE /upload/{file_id} purged its parsed rows with `Query.delete()`.

That emits one DELETE straight to the database and skips the ORM unit of work,
so `Mapper.after_delete` never fires and nothing lands in `sync_queue`. The rows
disappeared on this device and stayed in the other database forever — the same
silent divergence a raw-DB-API script causes, but from a normal API call.

`invoices`, `inventory` and `payments` are all in database/sync_map.py, so every
one of those deletions is supposed to be queued.
"""
import json
import os
import sys
import uuid

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_bizassist.db")
os.environ.setdefault("GROQ_API_KEY", "mock_groq_api_key")

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, backend_path)

from fastapi.testclient import TestClient           # noqa: E402
from sqlalchemy import text                          # noqa: E402
from main_groq import app                            # noqa: E402
from database.db import SessionLocal                 # noqa: E402
from database.models import Invoice, UploadedFile    # noqa: E402

client = TestClient(app)


def _signup():
    uname = f"up_{uuid.uuid4().hex[:8]}"
    r = client.post("/signup", json={
        "username": uname, "password": "TestPass123!", "business_name": "Purge Co",
    })
    assert r.status_code == 200, r.text
    return r.json()


def _queued_deletes(db, bid, entity):
    return db.execute(text(
        "SELECT entity_id FROM sync_queue "
        "WHERE business_id = :b AND entity = :e AND operation = 'DELETE'"
    ), {"b": bid, "e": entity}).fetchall()


def test_deleting_an_upload_queues_the_row_deletions():
    acct = _signup()
    auth = {"Authorization": f"Bearer {acct['token']}"}
    bid = acct["user"]["id"] if isinstance(acct.get("user"), dict) else acct["id"]

    db = SessionLocal()
    try:
        # The outbox only accepts rows for a HYBRID business — see
        # database/models.py::_queue_change. A local-only or cloud-only install
        # has nothing to push to, so without this the test would pass for the
        # wrong reason: nothing queued because nothing was ever meant to be.
        db.execute(text("UPDATE users SET settings = :s WHERE id = :b"), {
            "s": json.dumps({"general": {"hosting_mode": "hybrid"}}), "b": bid,
        })
        db.commit()

        up = UploadedFile(business_id=bid, filename="books.csv", file_type="invoice")
        db.add(up)
        db.commit()
        db.refresh(up)
        up_id = up.id            # read before the session closes

        inv = Invoice(
            business_id=bid, file_id=up_id, invoice_id=f"INV-{uuid.uuid4().hex[:6]}",
            customer="Someone", amount=100.0, status="paid",
        )
        db.add(inv)
        db.commit()
        invoice_id = inv.id

        # Clear the INSERT traffic so the assertion can only see the delete.
        db.execute(text("DELETE FROM sync_queue WHERE business_id = :b"), {"b": bid})
        db.commit()
    finally:
        db.close()

    r = client.delete(f"/upload/{up_id}", headers=auth)
    assert r.status_code == 200, r.text

    db = SessionLocal()
    try:
        assert db.query(Invoice).filter(Invoice.id == invoice_id).first() is None, \
            "the invoice should be gone locally"
        queued = _queued_deletes(db, bid, "invoices")
        assert queued, (
            "the invoice was deleted locally but nothing was queued — the other "
            "database will keep it forever"
        )
        assert invoice_id in [row[0] for row in queued]
    finally:
        db.close()
