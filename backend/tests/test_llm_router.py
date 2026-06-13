"""
tests/test_llm_router.py
========================
Unit tests for the NEW parallel LLM router (services/llm_router.py).
Pure unit tests — a fake client returns canned JSON; no Groq, no DB, no app
import, so this file runs standalone and the legacy pipeline is untouched.
"""
import os
import sys
import json
import logging

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, backend_path)

from services.llm_router import (  # noqa: E402
    classify, route, shadow_compare, RouteDecision, INTENTS, ACTIONS,
)


# ── fake Groq client ─────────────────────────────────────────────────────────

class _Msg:
    def __init__(self, content):
        self.content = content


class _Choice:
    def __init__(self, content):
        self.message = _Msg(content)


class _Resp:
    def __init__(self, content):
        self.choices = [_Choice(content)]
        self.usage = None


class _FakeClient:
    """Returns the given payload (dict → JSON, str → raw) for every call."""
    def __init__(self, payload):
        self._payload = payload
        self.calls = []
        outer = self

        class _Completions:
            def create(self, **kwargs):
                outer.calls.append(kwargs)
                p = outer._payload
                return _Resp(json.dumps(p) if isinstance(p, dict) else p)

        class _Chat:
            completions = _Completions()

        self.chat = _Chat()


def _d(payload):
    return classify("test query", client=_FakeClient(payload))


# ── mode → tier mapping ──────────────────────────────────────────────────────

def test_answer_with_intent_routes_direct():
    d = _d({"mode": "answer", "intent": "top_customers", "action": None,
            "entities": {}, "confidence": 0.9})
    assert d.tier == "DIRECT" and d.handler_key == "top_customers"


def test_advise_keeps_handler_for_grounding():
    """'Suggest loyalty offers' class: advise + the data intent that grounds it."""
    d = _d({"mode": "advise", "intent": "top_customers", "action": None,
            "entities": {}, "confidence": 0.85})
    assert d.tier == "AI_ADVISE" and d.handler_key == "top_customers"


def test_act_routes_to_gated_action():
    """'Escalate 90+ days' class: an ACTION preview, never a chat 'Done.'"""
    d = _d({"mode": "act", "intent": None, "action": "escalate_overdue",
            "entities": {"days_range": "90+"}, "confidence": 0.8})
    assert d.tier == "ACTION" and d.action == "escalate_overdue"
    assert d.entities["days_range"] == "90+"


def test_act_with_unknown_action_degrades_to_advise():
    """Unsafe to act on an unrecognised action — degrade, don't hallucinate."""
    d = _d({"mode": "act", "intent": None, "action": "delete_database",
            "entities": {}, "confidence": 0.9})
    assert d.mode == "advise" and d.tier == "AI_ADVISE" and d.action is None


def test_chat_and_analyze_tiers():
    assert _d({"mode": "chat", "confidence": 0.9}).tier == "CONVERSATIONAL"
    assert _d({"mode": "analyze", "confidence": 0.9}).tier == "AI_COMPLEX"


def test_answer_without_intent_falls_to_ai_simple():
    d = _d({"mode": "answer", "intent": None, "confidence": 0.4})
    assert d.tier == "AI_SIMPLE"


# ── validation hardening ─────────────────────────────────────────────────────

def test_unknown_intent_is_dropped_not_trusted():
    d = _d({"mode": "answer", "intent": "made_up_intent", "confidence": 0.9})
    assert d.intent is None and d.tier == "AI_SIMPLE"


def test_entity_extraction_passthrough_and_null_filtering():
    d = _d({"mode": "answer", "intent": "invoice_detail",
            "entities": {"invoice_id": "INV-0002", "customer": None,
                         "month": "", "bogus_key": "x"},
            "confidence": 0.9})
    assert d.entities == {"invoice_id": "INV-0002"}  # nulls + unknown keys dropped


def test_malformed_json_returns_none_never_raises():
    assert classify("q", client=_FakeClient("not json {{{")) is None


def test_bad_mode_returns_none():
    assert _d({"mode": "banana", "confidence": 0.9}) is None


def test_confidence_clamped():
    assert _d({"mode": "chat", "confidence": 7}).confidence == 1.0
    assert _d({"mode": "chat", "confidence": -3}).confidence == 0.0


def test_empty_query_short_circuits_without_calling_model():
    fc = _FakeClient({"mode": "chat"})
    assert classify("   ", client=fc) is None
    assert fc.calls == []


def test_route_returns_triple():
    tier, handler, d = route("q", client=_FakeClient(
        {"mode": "answer", "intent": "low_stock", "confidence": 0.9}))
    assert (tier, handler) == ("DIRECT", "low_stock")
    assert isinstance(d, RouteDecision)


# ── shadow comparison ────────────────────────────────────────────────────────

def _shadow_lines(payload, legacy, caplog):
    caplog.set_level(logging.INFO, logger="bizassist.llm_router")
    shadow_compare("test q", *legacy, client=_FakeClient(payload), sync=True)
    return [r.message for r in caplog.records if "[llm-shadow]" in r.message]


def test_shadow_agree_on_same_direct_handler(caplog):
    lines = _shadow_lines(
        {"mode": "answer", "intent": "top_customers", "confidence": 0.9},
        ("DIRECT", "top_customers", "top_customers"), caplog)
    assert lines and "AGREE" in lines[0]


def test_shadow_disagree_on_different_handler(caplog):
    lines = _shadow_lines(
        {"mode": "answer", "intent": "invoice_count", "confidence": 0.6},
        ("DIRECT", "customer_invoices", "overdue_amount"), caplog)
    assert lines and "DISAGREE" in lines[0]


def test_shadow_mode_upgrade_labelled(caplog):
    """Legacy sent 'suggest loyalty offers' DIRECT; llm says advise → upgrade."""
    lines = _shadow_lines(
        {"mode": "advise", "intent": "top_customers", "confidence": 0.85},
        ("DIRECT", "top_customers", "top_customers"), caplog)
    assert lines and "MODE-UPGRADE" in lines[0]


def test_shadow_error_logged_when_llm_unavailable(caplog):
    lines = _shadow_lines("garbage", ("AI_SIMPLE", None, "business_summary"), caplog)
    assert lines and "ERROR" in lines[0]


# ── registry sanity ──────────────────────────────────────────────────────────

def test_registries_are_nonempty_and_known_shape():
    assert len(INTENTS) >= 20 and "invoice_detail" in INTENTS
    assert "escalate_overdue" in ACTIONS
