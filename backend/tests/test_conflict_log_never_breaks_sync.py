"""
tests/test_conflict_log_never_breaks_sync.py
============================================
Production outage, business 126 / cloud 7 (BA-JABXGD): every push returned

    HTTP 500 … NotNullViolation: null value in column "entity_id" of relation
    "conflict_logs" … cloud_payload {"fk_col": "customer_id",
    "raw_value": 67874273, "parent_table": "customers", "action": "set_null"}

every 15 seconds, indefinitely, with the outbox frozen at 73 rows.

The cause was the DIAGNOSTIC, not the data. When `resolve_parent_fk_uids` cannot
verify a nullable FK it nulls the link and writes a `ConflictLog` so the owner
can find what lost its link (R-10). That insert used `data.get("id")` for a NOT
NULL column — and the receiving database strips the source primary key, because
it assigns its own. So the value was always NULL on that path.

Three things made it fatal rather than noisy:
  · `db.add()` only STAGES the row; the violation is raised at flush, outside
    the try/except that was supposed to contain it.
  · On Postgres a failed statement aborts the entire transaction (rule 58), so
    it took the whole push down, not just the log line.
  · The push is retried every cycle, so it never cleared on its own.

The rule this pins: best-effort telemetry must never be able to abort the sync
it is observing.
"""
import os
import sys
import uuid

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_bizassist.db")
os.environ.setdefault("GROQ_API_KEY", "mock_groq_api_key")

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, backend_path)

from fastapi.testclient import TestClient          # noqa: E402
from main_groq import app                           # noqa: E402
from database.db import SessionLocal                # noqa: E402
from database.models import ConflictLog, Invoice    # noqa: E402
from database.sync_map import resolve_parent_fk_uids  # noqa: E402

client = TestClient(app)


def _business():
    uname = f"cl_{uuid.uuid4().hex[:8]}"
    r = client.post("/signup", json={
        "username": uname, "password": "TestPass123!", "business_name": "Conflict Co",
    })
    assert r.status_code == 200, r.text
    acct = r.json()
    return acct["user"]["id"] if isinstance(acct.get("user"), dict) else acct["id"]


def test_unresolvable_fk_without_a_primary_key_does_not_break_the_session():
    """The exact production shape: an invoice payload with a customer_id that
    resolves to nothing, and NO `id` — because the receiver strips it."""
    bid = _business()
    db = SessionLocal()
    try:
        data = {
            "business_id": bid,
            "invoice_id": "INV-X",
            "customer_id": 67874273,      # the real value from the outage
            # NOTE: no "id" — this is the point.
        }

        deferred = resolve_parent_fk_uids(db, Invoice, data, business_id=bid)

        assert not deferred, "a nullable FK must not strand the row"
        assert data["customer_id"] is None, "the unverifiable link should be dropped"

        # THE ASSERTION THAT MATTERS: the session is still usable. Before the
        # fix this flush raised NotNullViolation on Postgres and poisoned the
        # whole push transaction.
        db.flush()
        db.commit()
    finally:
        db.close()


def test_a_resolvable_row_id_still_gets_its_conflict_log():
    """The diagnostic must survive the fix — when the payload DOES carry an id,
    the dropped link is still recorded and queryable."""
    bid = _business()
    db = SessionLocal()
    try:
        inv = Invoice(business_id=bid, invoice_id=f"INV-{uuid.uuid4().hex[:6]}",
                      customer="Someone", amount=10.0)
        db.add(inv)
        db.commit()

        before = db.query(ConflictLog).filter(ConflictLog.business_id == bid).count()

        data = {"id": inv.id, "business_id": bid, "customer_id": 67874273}
        resolve_parent_fk_uids(db, Invoice, data, business_id=bid)
        db.commit()

        after = db.query(ConflictLog).filter(ConflictLog.business_id == bid).count()
        assert after == before + 1, "the dropped link should still be recorded"

        row = (db.query(ConflictLog)
                 .filter(ConflictLog.business_id == bid)
                 .order_by(ConflictLog.id.desc()).first())
        assert row.resolution == "fk_nulled"
        assert row.entity_id == inv.id
    finally:
        db.close()
