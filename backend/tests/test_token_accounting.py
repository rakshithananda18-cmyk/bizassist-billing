"""
tests/test_token_accounting.py
==============================
Phase 0 regression tests — token truth + unified-path parity.

These lock in the fixes from the ai_router unification so they can't silently
regress:

  * meta.tokens reports REAL totals on AI answers (was hardcoded 0).
  * _polish tokens are counted (DIRECT answers surface their insight cost).
  * CONVERSATIONAL Groq calls are logged to TokenUsage (were invisible before).
  * /ask and /ask/stream resolve the same query to the same source (one pipeline).

Mirrors the mocking style of test_routing_tiers.py: patch routes.ask._client
so no real Groq call is made.
"""
import os
import sys
import json
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
from database.db import SessionLocal
from database.models import TokenUsage

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
    username = f"test_tokens_{uuid.uuid4().hex[:8]}"
    resp = client.post("/signup", json={
        "username": username,
        "password": "TestPass123!",
        "business_name": "Token Test Biz",
    })
    assert resp.status_code == 200, f"Signup failed: {resp.text}"
    body = resp.json()
    return {"headers": {"Authorization": f"Bearer {body['token']}"}}


def _mock_groq(text="Mocked answer.", prompt=120, completion=80):
    m = MagicMock()
    m.choices = [MagicMock(message=MagicMock(content=text, tool_calls=None))]
    m.usage = MagicMock(prompt_tokens=prompt, completion_tokens=completion)
    return m


def _token_row_count() -> int:
    db = SessionLocal()
    try:
        return db.query(TokenUsage).count()
    finally:
        db.close()


# ───────────────────────── token truth ─────────────────────────

@patch("routes.ask._client.chat.completions.create")
def test_ai_simple_reports_real_tokens(mock_create, auth):
    """AI_SIMPLE meta.tokens must equal the summed Groq usage, not 0."""
    invalidate()
    mock_create.return_value = _mock_groq("Your most reliable supplier is ...", 120, 80)
    # 'who is my most reliable supplier?' → topic business_summary (not an INTENT_DIRECT
    # topic, so no intent promotion) and not a COMPLEX trigger → genuine AI_SIMPLE.
    resp = client.post("/ask", json={"message": "who is my most reliable supplier?"},
                       headers=auth["headers"])
    assert resp.status_code == 200
    meta = resp.json()["meta"]
    assert meta["tokens"] == 200, f"expected real 200 tokens, got {meta['tokens']}"
    assert meta["cached"] is False


@patch("routes.ask._client.chat.completions.create")
def test_polish_tokens_counted_on_direct(mock_create, auth):
    """DIRECT answers now surface the _polish insight cost in meta.tokens."""
    invalidate()
    mock_create.return_value = _mock_groq("Insightful 2-liner.", 120, 80)
    resp = client.post("/ask", json={"message": "how many invoices do I have"},
                       headers=auth["headers"])
    assert resp.status_code == 200
    data = resp.json()
    assert data["source"] == "db"
    # polish made one Groq call (120+80) — that must be reflected, not hidden as 0
    assert data["meta"]["tokens"] == 200


@patch("routes.ask._client.chat.completions.create")
def test_conversational_logs_token_usage(mock_create, auth):
    """CONVERSATIONAL Groq calls must now write a TokenUsage row (C3 fix)."""
    invalidate()
    mock_create.return_value = _mock_groq("Hi there!", 30, 10)
    before = _token_row_count()
    resp = client.post("/ask", json={"message": "hi there"}, headers=auth["headers"])
    assert resp.status_code == 200
    assert resp.json()["source"] == "conversational"
    after = _token_row_count()
    assert after == before + 1, "conversational call should log exactly one TokenUsage row"


# ───────────────────────── unified-path parity ─────────────────────────

def _parse_sse_done(body: str) -> dict:
    """Return the parsed 'done' event payload from an SSE stream body."""
    done = None
    for line in body.splitlines():
        if not line.startswith("data:"):
            continue
        try:
            evt = json.loads(line[len("data:"):].strip())
        except json.JSONDecodeError:
            continue
        if evt.get("type") == "done":
            done = evt
    return done or {}


@patch("routes.ask._client.chat.completions.create")
def test_ask_and_stream_agree_on_direct_source(mock_create, auth):
    """The single pipeline => /ask and /ask/stream resolve DIRECT identically."""
    mock_create.return_value = _mock_groq("Insight.", 120, 80)

    invalidate()
    plain = client.post("/ask", json={"message": "total revenue"}, headers=auth["headers"])
    assert plain.status_code == 200
    assert plain.json()["source"] == "db"

    invalidate()
    streamed = client.post("/ask/stream", json={"message": "total revenue"}, headers=auth["headers"])
    assert streamed.status_code == 200
    done = _parse_sse_done(streamed.text)
    assert done.get("source") == "db", f"stream done event: {done}"
    # both paths carry the same instant-answer contract
    assert done.get("meta", {}).get("cached") is False
