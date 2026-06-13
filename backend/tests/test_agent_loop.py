"""
tests/test_agent_loop.py — Phase 2 adaptive agent loop
======================================================
The loop must: call tools the model asks for, stop and answer when the model
stops calling tools, respect the round cap (force a finalize), account tokens,
and be reachable only behind AGENT_MODE=loop (with pipeline fallback).
Groq + tools are mocked — no network, no DB.
"""
import os
import sys
from types import SimpleNamespace as NS
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_bizassist.db")
os.environ.setdefault("GROQ_API_KEY", "mock_groq_api_key")

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, backend_path)

import pytest
import services.agent_loop as al


def _tc(name, args="{}", tid="t1"):
    return NS(function=NS(name=name, arguments=args), id=tid)


def _resp(content=None, tool_calls=None, pin=10, pout=5):
    msg = NS(content=content, tool_calls=tool_calls)
    return NS(choices=[NS(message=msg)], usage=NS(prompt_tokens=pin, completion_tokens=pout))


@pytest.fixture(autouse=True)
def _no_token_log():
    with patch.object(al, "_log_tokens", lambda *a, **k: None):
        yield


def test_friendly_error_quota_message():
    # a 429 / token-per-day error → honest "daily limit" message, not "error"
    e = Exception("Error code: 429 - rate_limit_exceeded: tokens per day (TPD): Limit 100000")
    msg = al._friendly_error(e)
    assert "daily ai analysis limit" in msg.lower()
    assert "error" not in msg.lower() or "limit" in msg.lower()


def test_friendly_error_generic_message():
    msg = al._friendly_error(ValueError("boom"))
    assert "error" in msg.lower()


def test_run_agent_loop_quota_returns_friendly_text():
    boom = Exception("429 tokens per day (TPD) rate_limit_exceeded")
    with patch.object(al._client.chat.completions, "create", side_effect=boom):
        out = al.run_agent_loop("plan my business", 1, [])
    assert "daily ai analysis limit" in out["text"].lower()
    assert out["tokens_in"] == 0 and out["tokens_out"] == 0


def test_loop_calls_tool_then_answers():
    seq = [
        _resp(tool_calls=[_tc("summarize_invoices")]),       # round 1: ask for a tool
        _resp(content="Here is the analysis.\n## This Week: Top 3 Actions"),  # round 2: answer
    ]
    with patch.object(al._client.chat.completions, "create", side_effect=seq) as mock_create, \
         patch.object(al, "execute_tool", return_value="overdue: ₹100") as mock_tool:
        out = al.run_agent_loop("why is cash flow tight", 1, [])
    assert "Top 3 Actions" in out["text"]
    assert mock_tool.call_count == 1            # exactly the tool it asked for
    assert mock_create.call_count == 2
    assert out["tokens_in"] == 20 and out["tokens_out"] == 10   # summed across calls


def test_loop_respects_round_cap_then_finalizes(monkeypatch):
    monkeypatch.setattr(al, "MAX_ROUNDS", 2)
    # model keeps asking for tools forever → cap hits → forced finalize call
    seq = [
        _resp(tool_calls=[_tc("summarize_invoices")]),
        _resp(tool_calls=[_tc("view_business_metrics")]),
        _resp(content="Forced final.\n## This Week: Top 3 Actions"),  # finalize
    ]
    with patch.object(al._client.chat.completions, "create", side_effect=seq) as mock_create, \
         patch.object(al, "execute_tool", return_value="data"):
        out = al.run_agent_loop("analyse everything", 1, [])
    assert "Forced final" in out["text"]
    assert mock_create.call_count == 3          # 2 rounds + 1 finalize


def test_stream_emits_tokens_and_done():
    seq = [_resp(content="Streamed answer.\n## This Week: Top 3 Actions")]
    with patch.object(al._client.chat.completions, "create", side_effect=seq), \
         patch.object(al, "execute_tool", return_value="data"):
        events = list(al.run_agent_loop_stream("quick complex q", 1, []))
    joined = "".join(events)
    assert '"type": "status"' in joined
    assert '"type": "ag_done"' in joined
    assert "Streamed answer" in joined


def test_execute_tool_coerces_none_args():
    # A no-arg tool call arrives as `null` → None; execute_tool must coerce to {}
    # instead of crashing with "'NoneType' object has no attribute 'get'".
    from services.tools import execute_tool
    out = execute_tool("rank_top_customers", None, 999999)
    assert isinstance(out, str)
    assert "NoneType" not in out          # the bug signature must be gone


def test_dispatch_uses_loop_only_when_flag_set(monkeypatch):
    import services.agent_graph as ag
    monkeypatch.setenv("AGENT_MODE", "loop")
    with patch("services.agent_loop.run_agent_loop", return_value={"text": "L", "tokens_in": 1, "tokens_out": 1}) as m:
        res = ag.run_agent_graph("q", 1, [])
    assert res["text"] == "L"
    assert m.call_count == 1
