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

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_bizassist.db")
os.environ.setdefault("GROQ_API_KEY", "mock_groq_api_key")

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, backend_path)

from sqlalchemy import text, inspect

# Importing the app builds the schema (Base.metadata.create_all) on the test DB.
from main_groq import app  # noqa: F401  (side effect: create_all)
from database.db import SessionLocal, engine
from database.models import Customer

# The BusinessOwnedMixin tables that get `uid` in Phase A.
_UID_TABLES = [
    "customers", "vendors", "products", "invoices", "inventory", "payments",
    "purchase_orders", "purchase_invoices", "expenses", "godowns", "stock_transfers",
    "journal_entries", "period_locks",
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
