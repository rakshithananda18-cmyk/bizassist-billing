"""
tests/test_agent_graph_tokens.py
================================
Phase 0 / C1 regression — agent_graph token counts must live in graph STATE,
not a module-level global, so concurrent AI_COMPLEX runs can't corrupt each
other's token/billing data.
"""
import os
import sys

os.environ["DATABASE_URL"] = "sqlite:///./test_bizassist.db"
os.environ["GROQ_API_KEY"] = "mock_groq_api_key"

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, backend_path)

import pytest
from unittest.mock import patch, MagicMock
import services.agent_graph as ag


def _resp(content, prompt, completion):
    m = MagicMock()
    m.choices = [MagicMock(message=MagicMock(content=content))]
    m.usage = MagicMock(prompt_tokens=prompt, completion_tokens=completion)
    return m


def _blank_state():
    return {
        "user_query": "analyze my business", "business_id": 1, "history": [],
        "plan": {}, "invoice_result": "", "inventory_result": "",
        "payment_result": "", "final_response": "", "tokens_in": 0, "tokens_out": 0,
    }


def test_no_module_level_run_tokens():
    """The shared mutable global that caused the race must be gone."""
    assert not hasattr(ag, "_run_tokens"), "module-global _run_tokens must be removed (C1)"


def test_state_carries_token_fields():
    assert "tokens_in" in ag.AgentState.__annotations__
    assert "tokens_out" in ag.AgentState.__annotations__


@patch("services.agent_graph.client.chat.completions.create")
def test_planner_tokens_accumulate_in_state_not_global(mock_create):
    plan_json = '{"needs_invoice": false, "needs_inventory": false, "needs_payment": false, "overall_goal": "x"}'
    mock_create.return_value = _resp(plan_json, prompt=100, completion=20)

    s1 = ag.planner_node(_blank_state())
    assert s1["tokens_in"] == 100
    assert s1["tokens_out"] == 20

    # A second, independent run starts from its own zeroed state — no bleed.
    s2 = ag.planner_node(_blank_state())
    assert s2["tokens_in"] == 100, "independent run must not inherit prior run's tokens"
    assert s2["tokens_out"] == 20


@patch("services.agent_graph.client.chat.completions.create")
def test_synthesizer_adds_on_top_of_incoming_tokens(mock_create):
    mock_create.return_value = _resp("Final growth plan.", prompt=50, completion=30)

    s = _blank_state()
    s["tokens_in"], s["tokens_out"] = 100, 20   # as if planner already ran
    out = ag.synthesizer_node(s)

    assert out["tokens_in"] == 150, "synth must add to the tokens it received, not overwrite"
    assert out["tokens_out"] == 50
    assert out["final_response"] == "Final growth plan."
