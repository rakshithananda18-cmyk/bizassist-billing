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
from core.accounting.repost import repost_unposted_documents

client = TestClient(app)


def test_repost_missing_endpoint():
    """Verify POST /reports/integrity/repost-missing runs repost_unposted_documents
    successfully and returns a status 200 with summary counts."""
    # 1. Sign up owner
    owner_uname = f"owner_{uuid.uuid4().hex[:8]}"
    r_owner = client.post("/signup", json={"username": owner_uname, "password": "OwnerPass123!", "business_name": "Repost Test Biz"})
    assert r_owner.status_code == 200, r_owner.text
    headers = {"Authorization": f"Bearer {r_owner.json()['token']}"}

    # 2. Call POST /reports/integrity/repost-missing
    r_repost = client.post("/reports/integrity/repost-missing", headers=headers)
    assert r_repost.status_code == 200, r_repost.text
    res = r_repost.json()
    assert res["status"] == "success"
    assert "summary" in res
    assert "posted" in res["summary"]
    assert "existing" in res["summary"]
