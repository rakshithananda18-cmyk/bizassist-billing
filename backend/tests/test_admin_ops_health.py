"""
tests/test_admin_ops_health.py
==============================
Admin fleet observability — GET /admin/business/{id}/ops-health returns the same
per-tenant snapshot an owner sees, for ANY business, and is admin-only.
"""
import os

os.environ["DATABASE_URL"] = "sqlite:///./test_bizassist.db"
os.environ["GROQ_API_KEY"] = "mock_groq_api_key"

import sys
backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, backend_path)

import uuid
import pytest
from fastapi.testclient import TestClient
from main_groq import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def _clear_rl():
    from services.rate_limiter import _ip_window, _upload_window
    _ip_window.clear()
    _upload_window.clear()


def _admin_headers():
    r = client.post("/login", json={"username": "admin", "password": "admin123"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _signup():
    u = f"own_{uuid.uuid4().hex[:8]}"
    r = client.post("/signup", json={"username": u, "password": "TestPass123!",
                                     "business_name": "Fleet Co"})
    assert r.status_code == 200, r.text
    return r.json()


def test_admin_sees_business_ops_health():
    owner = _signup()
    ah = _admin_headers()
    r = client.get(f"/admin/business/{owner['id']}/ops-health", headers=ah)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["business_id"] == owner["id"]
    assert data["ok"] is True
    assert "sync" in data and "conflicts" in data and "integrity" in data and "ai_usage" in data


def test_non_admin_owner_is_blocked():
    owner = _signup()
    other = _signup()
    h = {"Authorization": f"Bearer {other['token']}"}
    r = client.get(f"/admin/business/{owner['id']}/ops-health", headers=h)
    assert r.status_code in (401, 403), r.text
