"""
tests/test_cache_regression.py
==============================
Regression for the cache-collision bug found in manual testing: two DIRECT
intents that `_detect_topic` lumps under the same topic ("how many invoices" and
"total revenue" both → 'total_revenue') must NOT share a cache entry, and a
writing task must not be served a cached data list.
"""
import os
import sys
import uuid
import logging

os.environ["DATABASE_URL"] = "sqlite:///./test_bizassist.db"
os.environ["GROQ_API_KEY"] = "mock_groq_api_key"

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, backend_path)

import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from main_groq import app
from services.context_cache import invalidate

client = TestClient(app)


@pytest.fixture(autouse=True)
def reset_state():
    invalidate()
    from services.rate_limiter import _ip_window, _upload_window, _minute_window
    _ip_window.clear(); _upload_window.clear(); _minute_window.clear()
    yield


@pytest.fixture(scope="module")
def auth():
    username = f"test_cachereg_{uuid.uuid4().hex[:8]}"
    resp = client.post("/signup", json={
        "username": username, "password": "TestPass123!", "business_name": "Cache Reg Biz",
    })
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['token']}"}


def _mock_polish(text="Insight line."):
    m = MagicMock()
    m.choices = [MagicMock(message=MagicMock(content=text, tool_calls=None))]
    m.usage = MagicMock(prompt_tokens=10, completion_tokens=5)
    return m


@patch("routes.ask._client.chat.completions.create")
def test_invoice_count_and_total_revenue_do_not_share_cache(mock_create, auth):
    """The reported bug: 'total revenue' returned the cached invoice-count answer."""
    invalidate()
    mock_create.return_value = _mock_polish()

    r1 = client.post("/ask", json={"message": "how many invoices do I have"}, headers=auth)
    r2 = client.post("/ask", json={"message": "total revenue"}, headers=auth)
    assert r1.status_code == 200 and r2.status_code == 200
    d1, d2 = r1.json(), r2.json()

    assert d1["source"] == "db" and d2["source"] == "db"
    # both detect topic 'total_revenue' but resolve to different handlers — the
    # second must NOT be the cached first answer.
    assert d2.get("meta", {}).get("cached") is not True
    assert d1["response"] != d2["response"], "total_revenue must not reuse the invoice_count cache"


@patch("routes.ask._client.chat.completions.create")
def test_top_debtors_not_served_overdue_list_cache(mock_create, auth):
    invalidate()
    mock_create.return_value = _mock_polish()

    r1 = client.post("/ask", json={"message": "show overdue invoices"}, headers=auth)
    r2 = client.post("/ask", json={"message": "who owes me the most"}, headers=auth)
    d1, d2 = r1.json(), r2.json()
    assert d1["source"] == "db" and d2["source"] in ("db", "intent")
    # the robust signal: with the bug r2 was a cache HIT on the overdue entry.
    assert d2.get("meta", {}).get("cached") is not True, "top_debtors must not hit the overdue_list cache"


@patch("routes.ask._client.chat.completions.create")
def test_debug_decision_log_exposes_matching_cache_disc(mock_create, auth, caplog):
    """At DEBUG, the [REQ ...] line shows handler + cache_disc; for a DIRECT query
    they MUST match (a mismatch is exactly the cache-collision bug)."""
    mock_create.return_value = _mock_polish()
    with caplog.at_level(logging.DEBUG, logger="bizassist.ai_router"):
        client.post("/ask", json={"message": "how many invoices do I have"}, headers=auth)
    req_lines = [r.message for r in caplog.records if r.message.startswith("[REQ ")]
    assert req_lines, "expected a [REQ ...] decision line at DEBUG level"
    line = req_lines[0]
    assert "handler=invoice_count" in line
    assert "cache_disc='invoice_count'" in line   # disc must equal handler for DIRECT
