"""
tests/test_sync_financial_conflicts.py
=======================================
P0 sync — surface financial conflicts instead of silently overwriting.

Before this change the sync/push "local wins" branch clobbered an existing
cloud row with NO trace, so a financial record edited on two devices lost one
version silently. Now, when a FINANCIAL entity's existing row is overwritten by
a differing local version, a ConflictLog(resolution='review_needed') is written
so the owner can see it — resolution behaviour (LWW still lands the data) is
unchanged.

Locks in:
  • pure `_payloads_differ` helper (ignores bookkeeping cols, string-compares)
  • local-wins on an invoice logs a review_needed conflict AND still applies
  • a no-op re-sync (same content) does NOT log a conflict
  • a non-financial entity (customers) local-wins does NOT log
  • GET /api/sync/conflicts surfaces unreviewed conflicts + a badge count
  • POST /api/sync/conflicts/{id}/resolve stamps resolved_at (data untouched)

Integration test via TestClient, mirroring tests/test_sync.py conventions.
"""
import os
import sys
import uuid
from datetime import datetime, timedelta

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_bizassist.db")
os.environ.setdefault("GROQ_API_KEY", "mock_groq_api_key")

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, backend_path)

from fastapi.testclient import TestClient
from main_groq import app
from database.db import SessionLocal, sync_disabled_var
from database.models import Invoice, Customer, ConflictLog
from routes.sync import _payloads_differ

client = TestClient(app)


def _signup(business_name):
    uname = f"own_{uuid.uuid4().hex[:8]}"
    r = client.post("/signup", json={
        "username": uname, "password": "TestPass123!", "business_name": business_name,
    })
    assert r.status_code == 200, r.text
    b = r.json()
    return {"headers": {"Authorization": f"Bearer {b['token']}"}, "bid": b["id"], "username": uname}


# ── pure helper ──────────────────────────────────────────────────────────────

def test_payloads_differ_ignores_bookkeeping_and_string_compares():
    base = {"id": 1, "total_amount": 100, "updated_at": "2026-01-01T00:00:00"}
    # only updated_at changed → NOT a meaningful diff
    assert _payloads_differ({"total_amount": 100, "updated_at": "2026-02-02T00:00:00"}, base) is False
    # 100 vs "100" across the SQLite/PG boundary → NOT a diff
    assert _payloads_differ({"total_amount": "100"}, base) is False
    # real value change → a diff
    assert _payloads_differ({"total_amount": 250}, base) is True


# ── integration: financial local-wins is surfaced ───────────────────────────

def _make_cloud_invoice(bid, number, total, when):
    """Create an invoice row directly, sync hooks disabled (simulates the cloud
    already holding a version). Returns its id."""
    db = SessionLocal()
    try:
        token = sync_disabled_var.set(True)
        try:
            inv = Invoice(business_id=bid, invoice_id=number, total_amount=total,
                          amount=total, status="Paid", updated_at=when)
            db.add(inv)
            db.commit()
            return inv.id
        finally:
            sync_disabled_var.reset(token)
    finally:
        db.close()


def _push(user, entity, entity_id, payload):
    body = {"changes": [{
        "entity": entity, "entity_id": entity_id, "operation": "UPDATE",
        "payload": payload, "created_at": datetime.utcnow().isoformat(),
    }]}
    r = client.post("/api/sync/push", headers=user["headers"], json=body)
    assert r.status_code == 200, r.text
    return r


def test_financial_local_wins_logs_review_needed_and_applies():
    user = _signup("Conflict Shop")
    cloud_when = datetime.utcnow() - timedelta(hours=1)
    inv_id = _make_cloud_invoice(user["bid"], f"INV-{uuid.uuid4().hex[:6]}", 100.0, cloud_when)

    # A NEWER local edit of the same invoice with a different amount.
    _push(user, "invoices", inv_id, {
        "id": inv_id, "total_amount": 275.0,
        "updated_at": datetime.utcnow().isoformat(),
    })

    db = SessionLocal()
    try:
        # Data landed (local wins under LWW) …
        inv = db.query(Invoice).filter(Invoice.id == inv_id).first()
        assert float(inv.total_amount) == 275.0
        # … AND it was surfaced, not silent.
        conf = (db.query(ConflictLog)
                .filter(ConflictLog.business_id == user["bid"],
                        ConflictLog.entity == "invoices",
                        ConflictLog.entity_id == inv_id)
                .first())
        assert conf is not None
        assert conf.resolution == "review_needed"
        assert conf.resolved_at is None
    finally:
        db.close()


def test_financial_noop_resync_does_not_log():
    user = _signup("NoOp Shop")
    cloud_when = datetime.utcnow() - timedelta(hours=1)
    inv_id = _make_cloud_invoice(user["bid"], f"INV-{uuid.uuid4().hex[:6]}", 100.0, cloud_when)

    # Same content, newer timestamp (normal re-propagation) → no conflict row.
    _push(user, "invoices", inv_id, {
        "id": inv_id, "total_amount": 100.0,
        "updated_at": datetime.utcnow().isoformat(),
    })

    db = SessionLocal()
    try:
        n = (db.query(ConflictLog)
             .filter(ConflictLog.business_id == user["bid"],
                     ConflictLog.entity_id == inv_id).count())
        assert n == 0
    finally:
        db.close()


def test_non_financial_local_wins_does_not_log():
    user = _signup("Cust Shop")
    db = SessionLocal()
    try:
        token = sync_disabled_var.set(True)
        try:
            c = Customer(business_id=user["bid"], name="Alice", phone="1",
                         updated_at=datetime.utcnow() - timedelta(hours=1))
            db.add(c); db.commit(); cid = c.id
        finally:
            sync_disabled_var.reset(token)
    finally:
        db.close()

    _push(user, "customers", cid, {
        "id": cid, "name": "Alice", "phone": "2",
        "updated_at": datetime.utcnow().isoformat(),
    })

    db = SessionLocal()
    try:
        n = (db.query(ConflictLog)
             .filter(ConflictLog.business_id == user["bid"],
                     ConflictLog.entity == "customers").count())
        assert n == 0   # customers is not a FINANCIAL entity
    finally:
        db.close()


def test_conflicts_route_lists_and_resolves():
    user = _signup("Route Shop")
    cloud_when = datetime.utcnow() - timedelta(hours=1)
    inv_id = _make_cloud_invoice(user["bid"], f"INV-{uuid.uuid4().hex[:6]}", 100.0, cloud_when)
    _push(user, "invoices", inv_id, {
        "id": inv_id, "total_amount": 500.0,
        "updated_at": datetime.utcnow().isoformat(),
    })

    r = client.get("/api/sync/conflicts", headers=user["headers"])
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["unreviewed_count"] >= 1
    assert any(c["entity"] == "invoices" and c["entity_id"] == inv_id for c in data["conflicts"])
    cid = next(c["id"] for c in data["conflicts"] if c["entity_id"] == inv_id)

    # Resolve it → drops out of the default (unreviewed) list.
    r2 = client.post(f"/api/sync/conflicts/{cid}/resolve", headers=user["headers"])
    assert r2.status_code == 200, r2.text
    r3 = client.get("/api/sync/conflicts", headers=user["headers"])
    assert all(c["id"] != cid for c in r3.json()["conflicts"])
