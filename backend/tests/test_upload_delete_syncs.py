"""
tests/test_upload_delete_syncs.py
=================================
C-6: DELETE /upload/{file_id} purged its parsed rows with `Query.delete()`.

That emits one DELETE straight to the database and skips the ORM unit of work,
so `Mapper.after_delete` never fires and nothing lands in `sync_queue`. The rows
disappeared on this device and stayed in the other database forever — the same
silent divergence a raw-DB-API script causes, but from a normal API call.

But only SOME of those deletions may cross the boundary. `invoices` and
`payments` are APPEND-ONLY (database/sync_map.py::APPEND_ONLY_DELETE_BLOCKLIST):
the receiver 422s a delete for them, and because that 422 covers the whole
payload and the outbox re-sends the same window every cycle, queueing one would
stall the business's sync permanently. `inventory` is not append-only, and that
is the deletion C-6 was genuinely losing.

So the two halves are tested separately: the syncable one must be queued, and
the append-only ones must not.
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
from database.models import Inventory, Invoice, UploadedFile   # noqa: E402

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
    body = r.json()
    assert body["kept"]["invoices"] == 1
    assert body["note"], "keeping the rows silently would be the worst of both"

    db = SessionLocal()
    try:
        # KEPT, not purged. Deleting it here would remove it on this device only
        # — `invoices` is append-only across the boundary, so the deletion can
        # never be replicated, and the cloud would hold it forever.
        assert db.query(Invoice).filter(Invoice.id == invoice_id).first() is not None, \
            "an accounting record must not be destroyed by deleting an import"

        # And nothing may be queued either: the receiver rejects a blocklisted
        # DELETE with a 422 covering the whole payload, and the outbox re-sends
        # the same window every cycle, so one such row stalls the business's
        # sync permanently.
        assert not _queued_deletes(db, bid, "invoices"), (
            "queued a DELETE for an append-only entity — the push endpoint will "
            "422 the entire batch and this business will stop syncing"
        )
        assert not _queued_deletes(db, bid, "payments")
    finally:
        db.close()


def test_cascade_never_wipes_the_ledger():
    """`cascade=true` on an invoice import used to delete EVERY invoice the
    business had — on one device only, unreplicable. That is the same rule as
    above in its most destructive form."""
    acct = _signup()
    auth = {"Authorization": f"Bearer {acct['token']}"}
    bid = acct["user"]["id"] if isinstance(acct.get("user"), dict) else acct["id"]

    db = SessionLocal()
    try:
        up = UploadedFile(business_id=bid, filename="books.csv", file_type="invoice")
        db.add(up)
        db.commit()
        db.refresh(up)
        up_id = up.id

        # An invoice from a DIFFERENT import entirely — cascade would take it too.
        other = Invoice(business_id=bid, invoice_id=f"INV-{uuid.uuid4().hex[:6]}",
                        customer="Unrelated", amount=50.0, status="paid")
        db.add(other)
        db.commit()
        other_id = other.id
    finally:
        db.close()

    r = client.delete(f"/upload/{up_id}?cascade=true", headers=auth)
    assert r.status_code == 200, r.text

    db = SessionLocal()
    try:
        assert db.query(Invoice).filter(Invoice.id == other_id).first() is not None, \
            "cascade wiped an unrelated invoice — the whole ledger was in scope"
    finally:
        db.close()


def test_deleting_an_upload_queues_a_syncable_row_deletion():
    """The other half: `inventory` is NOT append-only, so its delete must reach
    the outbox. This is the part of C-6 that was a genuine loss — the rows went
    locally and stayed in the other database forever."""
    acct = _signup()
    auth = {"Authorization": f"Bearer {acct['token']}"}
    bid = acct["user"]["id"] if isinstance(acct.get("user"), dict) else acct["id"]

    db = SessionLocal()
    try:
        db.execute(text("UPDATE users SET settings = :s WHERE id = :b"), {
            "s": json.dumps({"general": {"hosting_mode": "hybrid"}}), "b": bid,
        })
        db.commit()

        up = UploadedFile(business_id=bid, filename="stock.csv", file_type="inventory")
        db.add(up)
        db.commit()
        db.refresh(up)
        up_id = up.id

        item = Inventory(business_id=bid, file_id=up_id, product_name="Widget", stock=5.0)
        db.add(item)
        db.commit()
        item_id = item.id

        db.execute(text("DELETE FROM sync_queue WHERE business_id = :b"), {"b": bid})
        db.commit()
    finally:
        db.close()

    r = client.delete(f"/upload/{up_id}", headers=auth)
    assert r.status_code == 200, r.text

    db = SessionLocal()
    try:
        queued = _queued_deletes(db, bid, "inventory")
        assert item_id in [row[0] for row in queued], (
            "the inventory row was deleted locally but nothing was queued — the "
            "other database will keep it forever"
        )
    finally:
        db.close()
