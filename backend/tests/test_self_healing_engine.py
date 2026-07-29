import os
import sys
import uuid
import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_bizassist.db")
os.environ.setdefault("GROQ_API_KEY", "mock_groq_api_key")

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, backend_path)

from main_groq import app
from database.db import SessionLocal
from services.self_healing import (
    heal_hash_chain, heal_stock_ledger_drift, heal_sync_outbox_stalls,
    heal_staff_and_tenant_integrity, diagnose_and_heal_tenant
)

client = TestClient(app)


def test_master_self_healing_endpoint():
    """Verify POST /reports/integrity/self-heal executes all 4 repair domains cleanly and safely."""
    # 1. Sign up owner
    owner_uname = f"owner_{uuid.uuid4().hex[:8]}"
    r_owner = client.post("/signup", json={"username": owner_uname, "password": "OwnerPass123!", "business_name": "Self Healing Test Shop"})
    assert r_owner.status_code == 200, r_owner.text
    token = r_owner.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 2. Call POST /reports/integrity/self-heal
    r_heal = client.post("/reports/integrity/self-heal", headers=headers)
    assert r_heal.status_code == 200, r_heal.text
    res = r_heal.json()
    assert res["ok"] is True
    assert "hash_chain_healed" in res
    assert "stock_summary" in res
    assert "sync_summary" in res
    assert "staff_summary" in res
    assert "final_integrity" in res
