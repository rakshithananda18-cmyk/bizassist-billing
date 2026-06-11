"""
tests/test_shadow_routing.py  — Phase 1 Step 2
==============================================
Shadow mode runs the semantic router alongside the live regex router and logs
AGREE/DISAGREE — but must NOT change routing. The semantic classifier is mocked
so these tests don't load the embedding model.
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
    username = f"test_shadow_{uuid.uuid4().hex[:8]}"
    resp = client.post("/signup", json={
        "username": username, "password": "TestPass123!", "business_name": "Shadow Biz",
    })
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['token']}"}


@patch("routes.ask._client.chat.completions.create")
@patch("services.ai_router._semantic_classify")
def test_shadow_logs_disagreement_without_changing_routing(mock_sem, mock_create, auth, monkeypatch, caplog):
    monkeypatch.setenv("INTENT_ROUTER", "shadow")
    # semantic says overdue_list; regex/topic for "total revenue" is total_revenue → DISAGREE
    mock_sem.return_value = ("DIRECT", "overdue_list", 0.91)

    with caplog.at_level(logging.INFO, logger="bizassist.ai_router"):
        resp = client.post("/ask", json={"message": "total revenue"}, headers=auth)

    assert resp.status_code == 200
    # routing is UNCHANGED — the regex router still decided (source stays db)
    assert resp.json()["source"] == "db"
    # and a shadow line was logged
    shadow_lines = [r.message for r in caplog.records if "[ROUTER][shadow]" in r.message]
    assert shadow_lines, "expected a [ROUTER][shadow] log line in shadow mode"
    assert "DISAGREE" in shadow_lines[0]
    mock_sem.assert_called()


@patch("routes.ask._client.chat.completions.create")
@patch("services.ai_router._semantic_classify")
def test_shadow_logs_agreement(mock_sem, mock_create, auth, monkeypatch, caplog):
    monkeypatch.setenv("INTENT_ROUTER", "shadow")
    # semantic agrees with the detected topic for "total revenue"
    mock_sem.return_value = ("DIRECT", "total_revenue", 0.88)
    with caplog.at_level(logging.INFO, logger="bizassist.ai_router"):
        resp = client.post("/ask", json={"message": "total revenue"}, headers=auth)
    assert resp.status_code == 200
    shadow_lines = [r.message for r in caplog.records if "[ROUTER][shadow]" in r.message]
    assert shadow_lines and "AGREE" in shadow_lines[0]


@patch("routes.ask._client.chat.completions.create")
@patch("services.ai_router._semantic_classify")
def test_off_mode_is_silent_and_never_calls_semantic(mock_sem, mock_create, auth, monkeypatch, caplog):
    monkeypatch.setenv("INTENT_ROUTER", "off")
    with caplog.at_level(logging.INFO, logger="bizassist.ai_router"):
        resp = client.post("/ask", json={"message": "total revenue"}, headers=auth)
    assert resp.status_code == 200
    assert not any("[ROUTER][shadow]" in r.message for r in caplog.records)
    mock_sem.assert_not_called()
