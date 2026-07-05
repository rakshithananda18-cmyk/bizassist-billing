"""
tests/test_sync_shift_and_push_hardening.py
===========================================
Covers the hybrid-sync hardening work:

  1. register_shifts / shift_cash_movements now ENQUEUE and APPLY, so the
     invoices/invoice_payments that carry a shift_id FK stop deferring forever
     (the "N pending / Sync Error" stall).
  2. The cloud push route re-points the users FK (user_id → owner) for both
     shift tables so they don't FK-crash on the cloud.
  3. The client sync worker pushes in CHUNKS with a generous read timeout and
     banks progress per chunk (a mid-batch timeout no longer fails the whole
     outbox), guarded so pushes for one business never overlap.
  4. Idle hybrid businesses are skipped without a cloud probe or log line.
  5. Auth logs a rejected/stale token at INFO (routine re-auth), not WARN/ERROR.

Run:
    cd backend && python -m pytest tests/test_sync_shift_and_push_hardening.py -v
"""

import os
import sys
import uuid
import json
import logging
from datetime import datetime, timedelta

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_bizassist.db")
os.environ.setdefault("GROQ_API_KEY", "mock_groq_api_key")

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, backend_path)

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from main_groq import app
from database.db import SessionLocal, sync_disabled_var
from database.models import (
    Customer, Invoice, RegisterShift, ShiftCashMovement, SyncQueue, SyncLog, User,
)
import services.sync_worker as sw

client = TestClient(app)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _signup(business_name="Shift Sync Shop"):
    uname = f"own_{uuid.uuid4().hex[:8]}"
    r = client.post("/signup", json={
        "username": uname, "password": "TestPass123!", "business_name": business_name,
    })
    assert r.status_code == 200, r.text
    b = r.json()
    return {"headers": {"Authorization": f"Bearer {b['token']}"}, "bid": b["id"], "username": uname}


def _enable_hybrid(auth, interval=10):
    r = client.put("/settings", headers=auth["headers"], json={
        "general": {"hosting_mode": "hybrid", "sync_interval": interval}
    })
    assert r.status_code == 200, r.text


def _pending(bid, entity=None):
    db = SessionLocal()
    try:
        q = db.query(SyncQueue).filter(
            SyncQueue.business_id == bid, SyncQueue.synced_at.is_(None))
        if entity:
            q = q.filter(SyncQueue.entity == entity)
        return q.count()
    finally:
        db.close()


def _drain_queue(bid):
    """Mark every queued row for a business as already synced (empty outbox)."""
    db = SessionLocal()
    try:
        for row in db.query(SyncQueue).filter(SyncQueue.business_id == bid).all():
            row.synced_at = datetime.utcnow()
        db.commit()
    finally:
        db.close()


class _FakeResp:
    def __init__(self, status_code, json_data):
        self.status_code = status_code
        self._json = json_data
        self.text = json.dumps(json_data)

    def json(self):
        return self._json


def _ok_health(*a, **k):
    return _FakeResp(200, {"status": "ok"})


# ---------------------------------------------------------------------------
# 1. register_shifts now enqueues (the core fix)
# ---------------------------------------------------------------------------
def test_open_shift_enqueues_register_shift_when_hybrid():
    owner = _signup()
    _enable_hybrid(owner)

    r = client.post("/shifts/open", headers=owner["headers"], json={"opening_cash": 0})
    assert r.status_code == 201, r.text

    # Before the fix register_shifts was absent from _SYNC_TABLES, so no row was
    # ever queued and the child invoices deferred forever.
    assert _pending(owner["bid"], entity="register_shifts") == 1


# ---------------------------------------------------------------------------
# 2. push applies a shift and re-points the users FK to the owner
# ---------------------------------------------------------------------------
def _shift_change(bid, uid, user_id=999_999, updated_at=None):
    return {
        "entity": "register_shifts",
        "entity_id": 1,
        "operation": "INSERT",
        "payload": {
            "uid": uid,
            "business_id": bid,
            "user_id": user_id,                       # a source-DB id absent on "cloud"
            "start_time": datetime.utcnow().isoformat(),
            "status": "OPEN",
            "opening_cash": 0,
            "updated_at": (updated_at or datetime.utcnow()).isoformat(),
        },
        "created_at": datetime.utcnow().isoformat(),
    }


def test_push_applies_shift_and_repoints_user_fk():
    owner = _signup()
    uid = str(uuid.uuid4())

    r = client.post("/api/sync/push", headers=owner["headers"],
                    json={"changes": [_shift_change(owner["bid"], uid)]})
    assert r.status_code == 200, r.text
    assert r.json()["applied"] == 1

    db = SessionLocal()
    try:
        shift = db.query(RegisterShift).filter(RegisterShift.uid == uid).first()
        assert shift is not None
        # user_id was 999_999 on the wire; must be re-pointed to the owner so the
        # NOT NULL FK to users doesn't crash.
        assert shift.user_id == owner["bid"]
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 3. an invoice that references a shift DEFERS until the shift exists, then applies
# ---------------------------------------------------------------------------
def _invoice_change(bid, shift_uid):
    return {
        "entity": "invoices",
        "entity_id": 1,
        "operation": "INSERT",
        "payload": {
            "uid": str(uuid.uuid4()),
            "business_id": bid,
            "shift_uid": shift_uid,                    # parent-uid FK hint
            "invoice_id": f"SHIFTINV-{uuid.uuid4().hex[:6]}",
            "customer": "Walk-in",
            "invoice_date": "2026-07-06",
            "amount": 100.0,
            "total_amount": 100.0,
            "status": "Paid",
            "updated_at": datetime.utcnow().isoformat(),
        },
        "created_at": datetime.utcnow().isoformat(),
    }


def test_invoice_defers_until_shift_present_then_resolves():
    owner = _signup()
    shift_uid = str(uuid.uuid4())
    inv = _invoice_change(owner["bid"], shift_uid)

    # (a) push the invoice first — parent shift missing → DEFERRED, not applied.
    r1 = client.post("/api/sync/push", headers=owner["headers"], json={"changes": [inv]})
    assert r1.status_code == 200, r1.text
    assert r1.json()["applied"] == 0
    db = SessionLocal()
    try:
        assert db.query(Invoice).filter(Invoice.uid == inv["payload"]["uid"]).first() is None
    finally:
        db.close()

    # (b) push the parent shift.
    r2 = client.post("/api/sync/push", headers=owner["headers"],
                     json={"changes": [_shift_change(owner["bid"], shift_uid)]})
    assert r2.json()["applied"] == 1

    # (c) re-push the invoice — parent now resolvable → applies and links shift_id.
    r3 = client.post("/api/sync/push", headers=owner["headers"], json={"changes": [inv]})
    assert r3.json()["applied"] == 1
    db = SessionLocal()
    try:
        landed = db.query(Invoice).filter(Invoice.uid == inv["payload"]["uid"]).first()
        shift = db.query(RegisterShift).filter(RegisterShift.uid == shift_uid).first()
        assert landed is not None
        assert landed.shift_id == shift.id      # resolved to the LOCAL shift id
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 4. shift_cash_movements apply without an FK crash (user_id re-pointed)
# ---------------------------------------------------------------------------
def test_push_applies_shift_cash_movement_without_fk_crash():
    owner = _signup()
    shift_uid = str(uuid.uuid4())
    client.post("/api/sync/push", headers=owner["headers"],
                json={"changes": [_shift_change(owner["bid"], shift_uid)]})

    mv_uid = str(uuid.uuid4())
    mv = {
        "entity": "shift_cash_movements",
        "entity_id": 1,
        "operation": "INSERT",
        "payload": {
            "uid": mv_uid,
            "business_id": owner["bid"],
            "shift_uid": shift_uid,
            "user_id": 999_999,                        # absent on "cloud" → must repoint
            "movement_type": "paid_out",
            "category": "bank_deposit",
            "amount": 500.0,
            "updated_at": datetime.utcnow().isoformat(),
        },
        "created_at": datetime.utcnow().isoformat(),
    }
    r = client.post("/api/sync/push", headers=owner["headers"], json={"changes": [mv]})
    assert r.status_code == 200, r.text
    assert r.json()["applied"] == 1

    db = SessionLocal()
    try:
        row = db.query(ShiftCashMovement).filter(ShiftCashMovement.uid == mv_uid).first()
        assert row is not None
        assert row.user_id == owner["bid"]            # repointed, no FK crash
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 5. re-pushing the same shift uid is idempotent (no duplicate row)
# ---------------------------------------------------------------------------
def test_repush_same_shift_is_idempotent():
    owner = _signup()
    uid = str(uuid.uuid4())
    change = _shift_change(owner["bid"], uid)

    client.post("/api/sync/push", headers=owner["headers"], json={"changes": [change]})
    client.post("/api/sync/push", headers=owner["headers"], json={"changes": [change]})

    db = SessionLocal()
    try:
        assert db.query(RegisterShift).filter(RegisterShift.uid == uid).count() == 1
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 6. in-flight guard is a strict per-business mutex
# ---------------------------------------------------------------------------
def test_push_guard_is_reentrant_safe():
    bid = 987_654
    assert sw._try_acquire_push(bid) is True
    assert sw._try_acquire_push(bid) is False     # already held → refused
    sw._release_push(bid)
    assert sw._try_acquire_push(bid) is True       # released → available again
    sw._release_push(bid)


# ---------------------------------------------------------------------------
# 7. worker pushes in chunks and marks every item synced
# ---------------------------------------------------------------------------
def _make_customers(bid, n):
    db = SessionLocal()
    try:
        for i in range(n):
            db.add(Customer(business_id=bid, name=f"C{i}-{uuid.uuid4().hex[:5]}",
                            phone="9000000000", updated_at=datetime.utcnow()))
        db.commit()
    finally:
        db.close()


def test_worker_chunks_push_and_marks_all_synced(monkeypatch):
    owner = _signup()
    _enable_hybrid(owner)
    _drain_queue(owner["bid"])                     # clear the setup rows
    n = sw._PUSH_CHUNK_SIZE + 5                     # forces 2 chunks
    _make_customers(owner["bid"], n)

    sizes = []

    def fake_post(url, json=None, headers=None, timeout=None):
        sizes.append(len(json["changes"]))
        return _FakeResp(200, {"status": "success", "applied": len(json["changes"])})

    monkeypatch.setattr(sw.httpx, "get", _ok_health)
    monkeypatch.setattr(sw.httpx, "post", fake_post)
    sw._LAST_RUN.pop(owner["bid"], None)

    sw.trigger_sync_run(owner["bid"])

    assert sizes, "push was never attempted"
    assert all(s <= sw._PUSH_CHUNK_SIZE for s in sizes)   # no chunk over the cap
    assert sum(sizes) == n
    assert _pending(owner["bid"], entity="customers") == 0


# ---------------------------------------------------------------------------
# 8. a mid-batch timeout banks earlier chunks; the rest stay pending
# ---------------------------------------------------------------------------
def test_worker_chunk_failure_preserves_prior_chunks(monkeypatch):
    owner = _signup()
    _enable_hybrid(owner)
    _drain_queue(owner["bid"])
    n = sw._PUSH_CHUNK_SIZE + 5
    _make_customers(owner["bid"], n)

    calls = {"n": 0}

    def flaky_post(url, json=None, headers=None, timeout=None):
        calls["n"] += 1
        if calls["n"] == 1:
            return _FakeResp(200, {"status": "success", "applied": len(json["changes"])})
        raise Exception("The read operation timed out")   # 2nd chunk times out

    monkeypatch.setattr(sw.httpx, "get", _ok_health)
    monkeypatch.setattr(sw.httpx, "post", flaky_post)
    sw._LAST_RUN.pop(owner["bid"], None)

    sw.trigger_sync_run(owner["bid"])

    # First chunk banked, remainder still pending (progress preserved, not all-or-nothing).
    assert _pending(owner["bid"], entity="customers") == 5
    db = SessionLocal()
    try:
        failed = (db.query(SyncLog)
                  .filter(SyncLog.business_id == owner["bid"], SyncLog.status == "failed")
                  .count())
        assert failed >= 1
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 9. idle hybrid business is skipped without calling sync_business
# ---------------------------------------------------------------------------
def test_idle_hybrid_business_is_skipped(monkeypatch):
    owner = _signup()
    _enable_hybrid(owner)
    _drain_queue(owner["bid"])                     # empty outbox → idle
    sw._LAST_RUN.pop(owner["bid"], None)

    called = {}

    def spy(db, user, *a, **k):
        called[user.id] = True

    monkeypatch.setattr(sw, "sync_business", spy)
    sw.run_hybrid_sync()

    assert owner["bid"] not in called              # never entered the sync path
    assert owner["bid"] in sw._LAST_RUN            # but was stamped as checked


# ---------------------------------------------------------------------------
# 10. rejected/stale token logs at INFO, not WARN/ERROR
# ---------------------------------------------------------------------------
def test_invalid_token_logs_at_info(caplog):
    from services.auth import decode_access_token
    with caplog.at_level(logging.INFO, logger="bizassist.auth"):
        with pytest.raises(HTTPException) as ei:
            decode_access_token("not-a-real-jwt")
    assert ei.value.status_code == 401
    recs = [r for r in caplog.records if "invalid/stale token" in r.getMessage()]
    assert recs, "expected an INFO log for the rejected token"
    assert recs[0].levelno == logging.INFO
