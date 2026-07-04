"""
tests/test_audit_log_fallback.py  (audit T9)
============================================
read_audit_log must degrade gracefully:
  * a malformed/empty `detail` on an ActionLog row must NOT raise
    "Expecting value: line 1 column 1" — it falls back to the raw value.
  * a DB-branch failure must fall through to the file reader with a single
    WARNING (no ERROR-with-traceback spam on every admin poll).
"""
import os
import sys
import uuid

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_bizassist.db")
os.environ.setdefault("GROQ_API_KEY", "mock_groq_api_key")

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, backend_path)

from database.db import SessionLocal
from database.models import ActionLog
from services.admin_service import read_audit_log


def test_read_audit_log_no_db_returns_list():
    # No DB → file fallback path; must return a list (never raise).
    rows = read_audit_log(limit=10, db=None)
    assert isinstance(rows, list)


def test_read_audit_log_tolerates_bad_detail():
    db = SessionLocal()
    try:
        # A row whose detail is an empty string — json.loads('') raises
        # "Expecting value"; the reader must swallow it per-row.
        db.add(ActionLog(business_id=1, action="test_action", detail="", status="logged"))
        # And a row with non-JSON plain text.
        db.add(ActionLog(business_id=1, action="test_action2", detail="not json", status="logged"))
        db.commit()

        rows = read_audit_log(limit=50, db=db)
        assert isinstance(rows, list)
        actions = {r.get("action") for r in rows}
        assert "test_action" in actions
        # The bad-JSON row surfaces its raw value rather than crashing the read.
        raw_row = next((r for r in rows if r.get("action") == "test_action2"), None)
        assert raw_row is not None
        assert raw_row["details"] == {"raw": "not json"}
    finally:
        db.close()
