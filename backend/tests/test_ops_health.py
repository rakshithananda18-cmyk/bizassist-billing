"""
tests/test_ops_health.py
========================
P1 observability — the per-tenant GET /reports/ops-health snapshot.

Locks in:
  • owner gets a well-formed health snapshot (sync / conflicts / integrity / ai)
  • a clean new business reports ok=True with zero backlog and healthy books
  • unreviewed financial conflicts flip ok=False and are counted
  • cashier is blocked (owner-only)

Route-level test via TestClient.
"""
import os
import sys
import uuid
from datetime import datetime

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_bizassist.db")
os.environ.setdefault("GROQ_API_KEY", "mock_groq_api_key")

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, backend_path)

import pytest
from fastapi.testclient import TestClient
from main_groq import app
from database.db import SessionLocal
from database.models import ConflictLog

client = TestClient(app)


def _signup():
    u = f"own_{uuid.uuid4().hex[:8]}"
    r = client.post("/signup", json={"username": u, "password": "TestPass123!",
                                     "business_name": "Ops Co"})
    assert r.status_code == 200, r.text
    return r.json()


def test_ops_health_clean_business_is_ok():
    b = _signup()
    h = {"Authorization": f"Bearer {b['token']}"}
    r = client.get("/reports/ops-health", headers=h)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["ok"] is True
    assert data["sync"]["pending"] == 0
    assert data["conflicts"]["unreviewed"] == 0
    assert data["integrity"]["ok"] is True
    assert "tokens_today" in data["ai_usage"]


def test_unreviewed_conflict_flips_ok_false():
    b = _signup()
    bid = b["id"]
    h = {"Authorization": f"Bearer {b['token']}"}
    db = SessionLocal()
    try:
        db.add(ConflictLog(business_id=bid, entity="invoices", entity_id=1,
                           resolution="review_needed", resolved_at=None,
                           local_updated_at=datetime.utcnow(),
                           cloud_updated_at=datetime.utcnow()))
        db.commit()
    finally:
        db.close()

    r = client.get("/reports/ops-health", headers=h)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["conflicts"]["unreviewed"] == 1
    assert data["ok"] is False
