"""
tests/test_conflict_log_only_on_apply.py
========================================
A conflict is a record that was OVERWRITTEN. A row that never applied was never
overwritten, so it has no conflict to report.

Seen in the Ops panel: invoice #783 listed EIGHT times in "Financial edits synced
from another device", every copy carrying the same two timestamps to the
microsecond. Not a display bug — eight real ConflictLog rows.

`_apply_pulled_row` logged the conflict at the point LWW decided the cloud copy
won, which is BEFORE `resolve_parent_fk_uids` gets to defer the row for a missing
parent. A deferred row is never written, so the log described an overwrite that
had not happened; and the inbox retries a held row up to MAX_AUTO_ATTEMPTS (7)
times, so one invoice waiting on an absent customer wrote 1 + 7 = 8 identical
rows. The owner's review list filled with copies of a non-event, and the real
conflicts were buried among them.

The logging now happens after the deferral check and before the first field is
written — late enough that the overwrite is certain, early enough that the
snapshot is still of the losing version.
"""
import os
import sys
import uuid
from datetime import datetime, timedelta

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_bizassist.db")
os.environ.setdefault("GROQ_API_KEY", "mock_groq_api_key")

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, backend_path)

from fastapi.testclient import TestClient              # noqa: E402
from main_groq import app                              # noqa: E402
from database.db import SessionLocal                   # noqa: E402
from database.models import ConflictLog, Invoice, Customer  # noqa: E402
from services.sync_worker import _apply_pulled_row     # noqa: E402

client = TestClient(app)


def _signup(name="Conflict Co"):
    uname = f"cfl_{uuid.uuid4().hex[:8]}"
    r = client.post("/signup", json={
        "username": uname, "password": "TestPass123!", "business_name": name,
    })
    assert r.status_code == 200, r.text
    b = r.json()
    return (b["user"]["id"] if isinstance(b.get("user"), dict) else b["id"])


def _seed_invoice(db, bid, uid, number, updated_at):
    inv = Invoice(business_id=bid, uid=uid, invoice_id=number, customer="Someone",
                  amount=100.0, status="Pending", updated_at=updated_at)
    db.add(inv)
    db.commit()
    return inv


def _conflicts_for(db, bid):
    return db.query(ConflictLog).filter(ConflictLog.business_id == bid).count()


def test_a_deferred_row_logs_no_conflict():
    """The bug, reduced: a newer cloud invoice pointing at a customer this
    database has never seen. LWW says the cloud wins, the parent check says it
    cannot be written — and nothing may be recorded, on any attempt."""
    bid = _signup()
    db = SessionLocal()
    try:
        uid = str(uuid.uuid4())
        old = datetime(2026, 7, 3, 17, 44, 22)
        _seed_invoice(db, bid, uid, f"INV-{uuid.uuid4().hex[:6]}", old)
        before = _conflicts_for(db, bid)

        record = {
            "uid": uid,
            "invoice_id": "INV-CLOUD",
            "customer": "Edited on another device",
            "amount": 250.0,
            "status": "Paid",
            "updated_at": (old + timedelta(days=33)).isoformat(),
            # The parent this database does not have. Its presence is what makes
            # resolve_parent_fk_uids defer instead of apply.
            "customer_uid": str(uuid.uuid4()),
        }

        # Every retry the inbox would make, including the first attempt.
        for _ in range(8):
            res = _apply_pulled_row(db, bid, "invoices", Invoice, dict(record))
            assert res.status == "deferred", f"expected deferral, got {res.status}"

        assert _conflicts_for(db, bid) == before, (
            "a row that was never written recorded a conflict — this is the "
            "eight-copies-of-#783 bug")
    finally:
        db.rollback()
        db.close()


def test_a_real_overwrite_still_logs_exactly_one_conflict():
    """The guard must not swallow the thing it guards. Same invoice, same newer
    cloud copy, but the parent resolves — so the row applies and the losing
    local version has to be on record."""
    bid = _signup()
    db = SessionLocal()
    try:
        uid = str(uuid.uuid4())
        old = datetime(2026, 7, 3, 17, 44, 22)
        _seed_invoice(db, bid, uid, f"INV-{uuid.uuid4().hex[:6]}", old)
        before = _conflicts_for(db, bid)

        res = _apply_pulled_row(db, bid, "invoices", Invoice, {
            "uid": uid,
            "invoice_id": "INV-CLOUD-2",
            "customer": "Edited on another device",
            "amount": 250.0,
            "status": "Paid",
            "updated_at": (old + timedelta(days=33)).isoformat(),
        })
        db.commit()

        assert res.status == "applied", f"expected apply, got {res.status}"
        assert _conflicts_for(db, bid) == before + 1, (
            "moving the hook past the deferral check must not lose real conflicts")
    finally:
        db.rollback()
        db.close()


def test_an_insert_logs_no_conflict():
    """A row this database has never held cannot have a losing version. Covers
    the path where the conflict flag is never assigned — it has to be
    initialised, or a brand-new row raises NameError inside the savepoint."""
    bid = _signup()
    db = SessionLocal()
    try:
        before = _conflicts_for(db, bid)
        res = _apply_pulled_row(db, bid, "invoices", Invoice, {
            "uid": str(uuid.uuid4()),
            "invoice_id": f"INV-{uuid.uuid4().hex[:6]}",
            "customer": "Brand new",
            "amount": 10.0,
            "status": "Pending",
            "updated_at": datetime(2026, 8, 1, 9, 0, 0).isoformat(),
        })
        db.commit()
        assert res.status == "applied", f"expected apply, got {res.status}"
        assert _conflicts_for(db, bid) == before
    finally:
        db.rollback()
        db.close()
