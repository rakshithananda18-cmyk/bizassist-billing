"""
tests/test_router_switch.py
===========================
The LLM_ROUTER switch: off → legacy untouched; on → the LLM decision steers,
with the two new tiers behaving safely:

  AI_ADVISE  "suggest…" questions return grounded ADVICE (not a raw table)
  ACTION     "escalate…" returns a gated preview chip (never a fake "Done.")
  fallback   LLM router failure → legacy answers as always

Mirrors the mocking style of test_token_accounting.py.
"""
import os
import sys
import uuid

os.environ["DATABASE_URL"] = "sqlite:///./test_bizassist.db"
os.environ["GROQ_API_KEY"] = "mock_groq_api_key"

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, backend_path)

import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from main_groq import app
from services.context_cache import invalidate
from services.llm_router import RouteDecision

client = TestClient(app)


@pytest.fixture(autouse=True)
def reset_state(monkeypatch):
    invalidate()
    from services.rate_limiter import _ip_window, _upload_window, _minute_window
    from services.router_mode import reset_mode
    _ip_window.clear()
    _upload_window.clear()
    _minute_window.clear()
    monkeypatch.delenv("LLM_ROUTER", raising=False)
    reset_mode()          # clear any runtime override from previous tests
    yield
    reset_mode()


@pytest.fixture(scope="module")
def auth():
    username = f"test_switch_{uuid.uuid4().hex[:8]}"
    resp = client.post("/signup", json={
        "username": username, "password": "TestPass123!",
        "business_name": "Switch Test Biz",
    })
    assert resp.status_code == 200, f"Signup failed: {resp.text}"
    return {"headers": {"Authorization": f"Bearer {resp.json()['token']}"}}


def _mock_groq(text="Mocked.", prompt=100, completion=50):
    m = MagicMock()
    m.choices = [MagicMock(message=MagicMock(content=text, tool_calls=None))]
    m.usage = MagicMock(prompt_tokens=prompt, completion_tokens=completion)
    return m


# ── off: legacy untouched ────────────────────────────────────────────────────

@patch("services.llm_router.route")
@patch("routes.ask._client.chat.completions.create")
def test_off_never_calls_llm_router(mock_create, mock_route, auth, monkeypatch):
    monkeypatch.setenv("LLM_ROUTER", "off")
    mock_create.return_value = _mock_groq()
    resp = client.post("/ask", json={"message": "how many invoices do I have"},
                       headers=auth["headers"])
    assert resp.status_code == 200
    assert resp.json()["source"] == "db"      # legacy DIRECT as always
    mock_route.assert_not_called()


# ── on: AI_ADVISE returns grounded advice ────────────────────────────────────

@patch("services.llm_router.route")
@patch("routes.ask._client.chat.completions.create")
def test_on_advise_returns_advice_not_table(mock_create, mock_route, auth, monkeypatch):
    monkeypatch.setenv("LLM_ROUTER", "on")
    d = RouteDecision(mode="advise", intent="top_customers", confidence=0.9)
    mock_route.return_value = ("AI_ADVISE", "top_customers", d)
    mock_create.return_value = _mock_groq(
        "1. Offer Daily Needs Store a 2% early-payment discount …")
    resp = client.post("/ask",
                       json={"message": "Suggest loyalty offers for my top customers"},
                       headers=auth["headers"])
    assert resp.status_code == 200
    body = resp.json()
    assert body["source"] == "advice"
    assert body["meta"]["model_tier"] == "AI_ADVISE"
    assert "discount" in body["response"]
    assert body["meta"]["tokens"] > 0          # advice call counted


# ── on: ACTION returns a preview chip, never executes ────────────────────────

@patch("services.llm_router.route")
@patch("routes.ask._client.chat.completions.create")
def test_on_action_returns_preview_chip_not_done(mock_create, mock_route, auth, monkeypatch):
    monkeypatch.setenv("LLM_ROUTER", "on")
    d = RouteDecision(mode="act", action="escalate_overdue",
                      entities={"days_range": "90+"}, confidence=0.85)
    mock_route.return_value = ("ACTION", None, d)
    mock_create.return_value = _mock_groq("should not be needed")
    resp = client.post("/ask", json={"message": "Escalate 90+ days"},
                       headers=auth["headers"])
    assert resp.status_code == 200
    body = resp.json()
    assert body["source"] == "action"
    assert "confirm" in body["response"].lower()
    assert body["response"].strip().lower() != "done."
    chips = body["suggestions"]
    assert chips and chips[0]["type"] == "action"
    assert chips[0]["action"] == "escalate_overdue"
    # The chat LLM was never asked to fake an action
    mock_create.assert_not_called()


# ── on: LLM failure → legacy fallback ────────────────────────────────────────

@patch("services.llm_router.route", return_value=None)
@patch("routes.ask._client.chat.completions.create")
def test_on_falls_back_to_legacy_when_llm_fails(mock_create, mock_route, auth, monkeypatch):
    monkeypatch.setenv("LLM_ROUTER", "on")
    mock_create.return_value = _mock_groq()
    resp = client.post("/ask", json={"message": "total revenue"},
                       headers=auth["headers"])
    assert resp.status_code == 200
    assert resp.json()["source"] == "db"      # legacy DIRECT answered
    mock_route.assert_called_once()
