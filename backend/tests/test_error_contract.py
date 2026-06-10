"""
tests/test_error_contract.py
============================
Phase 0 / H1 — /ask must signal failure with a real HTTP status code and the
canonical error envelope, not a 200-OK body carrying {"status_code": 429}.
"""
import os
import sys
import uuid

os.environ["DATABASE_URL"] = "sqlite:///./test_bizassist.db"
os.environ["GROQ_API_KEY"] = "mock_groq_api_key"

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, backend_path)

import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient
from main_groq import app
from services.context_cache import invalidate

client = TestClient(app)


@pytest.fixture(autouse=True)
def reset_state():
    invalidate()
    from services.rate_limiter import _ip_window, _upload_window, _minute_window
    _ip_window.clear()
    _upload_window.clear()
    _minute_window.clear()
    yield


@pytest.fixture(scope="module")
def auth():
    username = f"test_err_{uuid.uuid4().hex[:8]}"
    resp = client.post("/signup", json={
        "username": username, "password": "TestPass123!", "business_name": "Err Biz",
    })
    assert resp.status_code == 200, f"Signup failed: {resp.text}"
    return {"Authorization": f"Bearer {resp.json()['token']}"}


@patch("services.ai_router.check_rate_limit")
def test_ask_rate_limit_returns_real_429(mock_rl, auth):
    mock_rl.return_value = {
        "allowed": False,
        "reason": "Rate limit: max 30 requests per minute.",
        "limit": 30, "used": 31, "retry_after": 42,
    }
    resp = client.post("/ask", json={"message": "total revenue"}, headers=auth)

    # The HTTP status itself signals failure now — not a 200 body.
    assert resp.status_code == 429
    body = resp.json()
    assert body["code"] == "rate_limited"
    assert "error" in body and isinstance(body["error"], str)
    assert body["retry_after"] == 42
    # the misleading in-body status_code field is gone
    assert "status_code" not in body


@patch("routes.ask._client.chat.completions.create")
def test_ask_success_still_returns_200_envelope(mock_create, auth):
    """The success contract is unchanged — only the error path moved to real codes."""
    resp = client.post("/ask", json={"message": "total revenue"}, headers=auth)
    assert resp.status_code == 200
    data = resp.json()
    assert data["source"] == "db"
    assert "error" not in data
