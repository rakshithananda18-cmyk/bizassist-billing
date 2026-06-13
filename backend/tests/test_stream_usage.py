"""
tests/test_stream_usage.py
==========================
R1 regression tests — streamed responses must log REAL token usage.

Before this fix, streamed Groq calls (the React client's main path) exposed no
usage object, so CONVERSATIONAL-stream logged nothing and AI_SIMPLE-stream
missed its final round → daily budgets drifted optimistic. Now every streamed
call requests `stream_options={"include_usage": True}`; the usage arrives on a
final choices-less chunk and is logged via _log_token_usage. If no usage chunk
appears, a character-count estimate is logged instead of 0.

Also covers the daily-digest upgrade: the morning summary leads with grounded,
NAMED "Today's Focus" items from the insights engine instead of bare counts.

Mirrors the mocking style of test_token_accounting.py.
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
    username = f"test_stream_{uuid.uuid4().hex[:8]}"
    resp = client.post("/signup", json={
        "username": username,
        "password": "TestPass123!",
        "business_name": "Stream Test Biz",
    })
    assert resp.status_code == 200, f"Signup failed: {resp.text}"
    body = resp.json()
    return {"headers": {"Authorization": f"Bearer {body['token']}"}}


# ── chunk builders (usage MUST be explicitly None on token chunks — a bare
#    MagicMock auto-creates attributes and would defeat the `is None` check) ──

def _token_chunk(text: str):
    return MagicMock(choices=[MagicMock(delta=MagicMock(content=text))], usage=None)


def _usage_chunk(prompt: int, completion: int):
    return MagicMock(choices=[],
                     usage=MagicMock(prompt_tokens=prompt, completion_tokens=completion))


def _nonstream_resp(text="Mocked.", prompt=120, completion=80, tool_calls=None):
    m = MagicMock()
    m.choices = [MagicMock(message=MagicMock(content=text, tool_calls=tool_calls))]
    m.usage = MagicMock(prompt_tokens=prompt, completion_tokens=completion)
    return m


def _token_rows():
    db = SessionLocal()
    try:
        return db.query(TokenUsage).count()
    finally:
        db.close()


def _parse_done(body: str) -> dict:
    done = {}
    for line in body.splitlines():
        if not line.startswith("data:"):
            continue
        try:
            evt = json.loads(line[len("data:"):].strip())
        except json.JSONDecodeError:
            continue
        if evt.get("type") == "done":
            done = evt
    return done


# ───────────────────── streamed usage is logged ─────────────────────

@patch("routes.ask._client.chat.completions.create")
def test_conversational_stream_logs_real_usage(mock_create, auth):
    """A streamed conversational reply logs the usage from the final chunk."""
    def _create(**kwargs):
        if kwargs.get("stream"):
            assert kwargs.get("stream_options") == {"include_usage": True}
            return iter([_token_chunk("Hello "), _token_chunk("there!"),
                         _usage_chunk(30, 10)])
        return _nonstream_resp("Hi!")
    mock_create.side_effect = _create

    before = _token_rows()
    resp = client.post("/ask/stream", json={"message": "hi there"}, headers=auth["headers"])
    assert resp.status_code == 200
    done = _parse_done(resp.text)
    assert done.get("source") == "conversational"
    assert done.get("meta", {}).get("tokens") == 40, f"done meta: {done.get('meta')}"
    assert _token_rows() == before + 1, "streamed conversational must log one TokenUsage row"


@patch("routes.ask._client.chat.completions.create")
def test_conversational_stream_estimates_when_no_usage(mock_create, auth):
    """No usage chunk exposed → log a character-count ESTIMATE, never 0."""
    def _create(**kwargs):
        if kwargs.get("stream"):
            return iter([_token_chunk("Hello, how can I help you today?")])
        return _nonstream_resp("Hi!")
    mock_create.side_effect = _create

    before = _token_rows()
    resp = client.post("/ask/stream", json={"message": "hello hello"}, headers=auth["headers"])
    assert resp.status_code == 200
    done = _parse_done(resp.text)
    assert done.get("meta", {}).get("tokens", 0) > 0, "estimate must be non-zero"
    assert _token_rows() == before + 1


@patch("routes.ask._client.chat.completions.create")
def test_ai_simple_stream_counts_both_rounds(mock_create, auth):
    """
    AI_SIMPLE stream = one non-stream tool round (120+80) + one streamed final
    round (30+10). meta.tokens must be the SUM (240), and both rounds must be in
    TokenUsage — this was the main undercount before R1.
    """
    def _create(**kwargs):
        if kwargs.get("stream"):
            return iter([_token_chunk("Your supplier "), _token_chunk("analysis."),
                         _usage_chunk(30, 10)])
        return _nonstream_resp("no tools needed", 120, 80, tool_calls=None)
    mock_create.side_effect = _create

    before = _token_rows()
    resp = client.post("/ask/stream",
                       json={"message": "who is my most reliable supplier?"},
                       headers=auth["headers"])
    assert resp.status_code == 200
    done = _parse_done(resp.text)
    assert done.get("source") == "ai"
    assert done.get("meta", {}).get("tokens") == 240, f"done meta: {done.get('meta')}"
    assert _token_rows() == before + 2, "both the tool round and the streamed final round must log"


# ───────────────────── digest leads with grounded focus ─────────────────────

def test_daily_summary_includes_todays_focus(auth):
    """The morning digest names actual items via the insights engine."""
    sent = {}

    def _capture_notify(email, whatsapp, subject, body):
        sent["subject"], sent["body"] = subject, body
        return True

    fake_panel = {
        "has_data": True,
        "positives": [],
        "improvements": [
            {"title": "Overdue cash to collect",
             "detail": "₹66,251 overdue across 6 invoices.",
             "action": "Chase top debtors first.", "dimension": "collections"},
            {"title": "Stock expiring soon",
             "detail": "2 item(s) expire within 30 days (e.g. Amul Butter in 12d).",
             "action": "Promote before it spoils.", "dimension": "products"},
        ],
    }

    cfg = {
        "business_id": 999999, "business_name": "Digest Test Biz",
        "email": "owner@example.com", "whatsapp_number": None,
        "alert_overdue": True, "alert_low_stock": True, "alert_expiry": True,
        "alert_daily_summary": True,
        "low_stock_threshold": 10, "expiry_days_threshold": 30,
    }

    with patch("services.alert_jobs._load_active_configs", return_value=[cfg]), \
         patch("services.alert_jobs.notify", side_effect=_capture_notify), \
         patch("services.smart_insights.build_panel_insights", return_value=fake_panel):
        from services.alert_jobs import run_daily_summary
        run_daily_summary()

    assert "body" in sent, "digest was not dispatched"
    assert "Today's Focus" in sent["body"]
    assert "₹66,251" in sent["body"], "focus items must carry the grounded figure"
    assert "Chase top debtors first." in sent["body"]
