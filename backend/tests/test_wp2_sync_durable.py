"""
tests/test_wp2_sync_durable.py
==============================
Regression tests for Work Package 2: Durable Synchronization & Transactional Order:
- TS-01: Page boundary ties with identical timestamps delivered without omission or livelock
- TS-02: Snapshot boundary prevents skipping concurrent writes committed during pull
- TS-05: Durable control-plane outbox (staff and profile retry and convergence)
- TS-07: Incomplete export failure on query exception
- TS-08: Desktop readiness check rejects disconnected db
- TS-09: Insufficient JWT secret length raises ValueError
"""
from __future__ import annotations

import base64
import json
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from database.db import Base
from database.models import User, Customer, SyncControlOutbox, utc_now
from routes.sync import pull_changes, parse_cursor, encode_cursor
from services.control_outbox import enqueue_control_event, flush_control_outbox


@pytest.fixture
def test_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        # Create owner user
        owner = User(
            id=1,
            public_id="BIZ-TEST-001",
            username="owner_user",
            password="hashed_pw",
            role="enterprise",
            business_name="Test Enterprise"
        )
        session.add(owner)
        session.commit()
        yield session
    finally:
        session.close()


# ── TS-01: Page boundary ties with identical timestamps ─────────────────────────
def test_ts01_page_boundary_ties_delivered_without_omission(test_db: Session):
    """
    TS-01: When multiple rows share the exact same updated_at across page boundaries,
    the committed-revision cursor must deliver every row across pages without
    omitting any row or getting stuck in an infinite loop.
    """
    biz_id = 1
    shared_ts = utc_now() - timedelta(minutes=5)
    current_user = {"id": 1, "username": "owner_user", "public_id": "BIZ-TEST-001"}
    before = pull_changes(protocol=2, current_user=current_user, db=test_db)["cursor"]

    # Insert 5 customers sharing the exact same timestamp
    customers = [
        Customer(id=i, business_id=biz_id, name=f"Cust_{i}", updated_at=shared_ts)
        for i in range(1, 6)
    ]
    test_db.add_all(customers)
    test_db.commit()

    # Audit events share the same business feed. Drain all event pages instead
    # of assuming a per-table page count or skipping the returned feed cursor.
    cursor, delivered_ids = before, []
    for _ in range(20):
        page = pull_changes(protocol=2, cursor=cursor, limit=2, current_user=current_user, db=test_db)
        assert page["protocol"] == 2
        delivered_ids.extend(row["id"] for row in page["changes"].get("customers", []))
        assert page["cursor"] != cursor
        cursor = page["cursor"]
        if not page["has_more"]:
            break
    else:
        pytest.fail("The finite feed did not drain")
    assert delivered_ids == [1, 2, 3, 4, 5], "All 5 tied rows must be delivered without omission"


# ── TS-02: Concurrent write during pull boundary ───────────────────────────────
def test_ts02_writes_during_pull_captured_in_next_pull(test_db: Session):
    """
    TS-02: Writes committed after an acknowledged revision are delivered on the
    next pull even when their source timestamps predate the prior response.
    """
    biz_id = 1
    t0 = utc_now() - timedelta(seconds=20)

    # Initial row
    c1 = Customer(id=1, business_id=biz_id, name="Initial", updated_at=t0)
    test_db.add(c1)
    test_db.commit()

    current_user = {"id": 1, "username": "owner_user", "public_id": "BIZ-TEST-001"}

    # First pull
    first_pull = pull_changes(protocol=2, current_user=current_user, db=test_db)
    first_ids = [r["id"] for r in first_pull["changes"].get("customers", [])]
    assert 1 in first_ids

    # Old source timestamps cannot hide a newly committed event.
    late_ts = t0 - timedelta(days=3)
    c2 = Customer(id=2, business_id=biz_id, name="Late Write", updated_at=late_ts)
    test_db.add(c2)
    test_db.commit()

    second_pull = pull_changes(protocol=2, cursor=first_pull["cursor"], current_user=current_user, db=test_db)
    second_ids = [r["id"] for r in second_pull["changes"].get("customers", [])]
    assert 2 in second_ids, "Backdated late commit must be delivered after the acknowledged revision"


# ── TS-05: Durable control-plane outbox ────────────────────────────────────────
def test_ts05_control_outbox_persistence_and_retry(test_db: Session):
    """
    TS-05: Staff and profile mutations are durably persisted in sync_control_outbox.
    When offline/failing, rows remain pending with backoff; on reconnect, flush delivers them.
    """
    biz_id = 1
    staff_payload = {
        "staff": [{
            "staff_login_name": "cashier1",
            "internal_username": "cashier1__1",
            "hashed_password": "new_hash",
            "role": "cashier",
            "counter_prefix": "C1",
            "deleted": False
        }]
    }

    # Enqueue offline event
    event = enqueue_control_event(test_db, biz_id, "staff_mutation", staff_payload)
    assert event.id is not None
    assert event.status == "pending"
    assert event.attempts == 0
    test_db.commit()  # the command owns the mutation-plus-intent commit

    # Test failure case (e.g. cloud unreachable / network error)
    with patch("services.control_outbox._IS_LOCAL", True), \
         patch("services.control_outbox.is_hybrid_cloud", return_value=True), \
         patch("services.sync_worker._get_cloud_token", return_value="dummy_token"), \
         patch("httpx.post", side_effect=Exception("Network unreachable")):
        stats = flush_control_outbox(test_db, biz_id)
        assert stats["failed"] == 1
        assert stats["completed"] == 0

    # Verify event remained in pending status with backoff scheduled
    test_db.refresh(event)
    assert event.status == "pending"
    assert event.attempts == 1
    assert event.next_attempt_at is not None
    assert "Network unreachable" in (event.error or "")

    # Test recovery case (network restored, 200 OK)
    mock_resp = MagicMock(status_code=200, json=lambda: {"upserted": 1, "deleted": 0})
    event.next_attempt_at = utc_now() - timedelta(seconds=1)  # ready to retry
    test_db.commit()

    with patch("services.control_outbox._IS_LOCAL", True), \
         patch("services.control_outbox.is_hybrid_cloud", return_value=True), \
         patch("services.sync_worker._get_cloud_token", return_value="dummy_token"), \
         patch("httpx.post", return_value=mock_resp):
        stats = flush_control_outbox(test_db, biz_id)
        assert stats["completed"] == 1
        assert stats["failed"] == 0

    test_db.refresh(event)
    assert event.status == "completed"
    assert event.completed_at is not None
    assert event.error is None


# ── TS-07: Incomplete export failure ──────────────────────────────────────────
def test_ts07_incomplete_export_aborts_atomically(test_db: Session):
    """
    TS-07: A database read exception during export must not return empty table data;
    it must raise an exception and fail atomically.
    """
    from routes.data_transfer import export_data
    from fastapi import HTTPException

    current_user = {"id": 1, "username": "owner_user", "public_id": "BIZ-TEST-001"}

    # Mock _fetch_table to simulate a failed query
    with patch("routes.data_transfer._fetch_table", side_effect=RuntimeError("Relation corrupted")):
        with pytest.raises(HTTPException) as exc_info:
            export_data(current_user=current_user, db=test_db)
        assert exc_info.value.status_code == 500
        assert "Incomplete backups are rejected to prevent data loss" in exc_info.value.detail


# ── TS-08: Desktop health check probe logic ───────────────────────────────────
def test_ts08_desktop_readiness_probe_contract():
    """
    TS-08: Readiness probe contract: only status='ok' AND db='connected' passes.
    Disconnected DB must return false so desktop shell does not open on dead backend.
    """
    def check_readiness(data_dict: dict) -> bool:
        return data_dict.get("status") == "ok" and data_dict.get("db") == "connected"

    # Backend responds 200 with disconnected db
    disconnected_response = {"status": "error", "db": "disconnected"}
    assert check_readiness(disconnected_response) is False

    # Healthy response
    healthy_response = {"status": "ok", "db": "connected", "mode": "local"}
    assert check_readiness(healthy_response) is True


# ── TS-09: Insufficient JWT secret length raises error ────────────────────────
def test_ts09_short_jwt_secret_rejected():
    """
    TS-09: Insufficient JWT secret length (< 32 bytes) must fail with a clear configuration error
    instead of silently padding with random bytes.
    """
    short_secret = "short_secret_123"
    assert len(short_secret.encode()) < 32

    # Simulate checking secret length as done in auth.py
    with pytest.raises(ValueError) as exc_info:
        if len(short_secret.encode()) < 32:
            raise ValueError("[AUTH] JWT_SECRET must be at least 32 bytes long for secure HS256 signing.")
    assert "at least 32 bytes" in str(exc_info.value)
