"""
tests/test_intent_router.py  — Phase 1
======================================
Two layers:

1. Mechanics (fast, no model): inject a trivial encoder + tiny seed set and
   verify the nearest-example match, the confidence threshold/fallback, and the
   tier mapping all work.

2. Scored eval (real MiniLM, skipped if sentence-transformers isn't installed):
   classify held-out phrasings (different wording from the seeds) and assert the
   router clears a modest accuracy bar. This is the harness we'll tighten before
   wiring the router into the request path.
"""
import os
import sys

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_bizassist.db")
os.environ.setdefault("GROQ_API_KEY", "mock_groq_api_key")

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, backend_path)

import pytest
from services.intent_router import SemanticRouter


# ───────────────────────── 1. mechanics (no model) ─────────────────────────

_VECS = {
    # seed phrases → basis vectors
    "OWE":   [1.0, 0.0, 0.0],
    "GREET": [0.0, 1.0, 0.0],
    "PLAN":  [0.0, 0.0, 1.0],
    # queries
    "who owes me":      [0.9, 0.1, 0.0],   # ~overdue
    "hello friend":     [0.1, 0.9, 0.0],   # ~conversational
    "growth strategy":  [0.0, 0.1, 0.9],   # ~complex
    "totally unrelated":[0.5, 0.5, 0.5],   # equidistant → low confidence
}

_SEED_TINY = {
    "overdue_list":   ["OWE"],
    "conversational": ["GREET"],
    "ai_complex":     ["PLAN"],
}


def _fake_encode(text):
    return _VECS[text]


def _router():
    return SemanticRouter(encode=_fake_encode, seed=_SEED_TINY, threshold=0.8)


def test_nearest_example_maps_to_tier_and_intent():
    tier, intent, conf = _router().classify("who owes me")
    assert (tier, intent) == ("DIRECT", "overdue_list")
    assert conf > 0.8


def test_conversational_and_complex_buckets():
    assert _router().classify("hello friend")[0] == "CONVERSATIONAL"
    assert _router().classify("growth strategy")[0] == "AI_COMPLEX"


def test_low_confidence_falls_back_to_ai_simple():
    tier, intent, conf = _router().classify("totally unrelated")
    assert tier == "AI_SIMPLE"
    assert intent is None
    assert conf < 0.8


def test_empty_query_is_ai_simple():
    assert _router().classify("   ")[:2] == ("AI_SIMPLE", None)


# ───────────────────────── 2. scored eval (real model) ─────────────────────

# (query, expected_tier, expected_intent_or_None) — held-out phrasings, distinct
# from the seed phrases, ~2 per intent so accuracy is a meaningful number.
_EVAL_CASES = [
    # overdue
    ("show me everyone who is behind on payments", "DIRECT", "overdue_list"),
    ("which clients still haven't cleared their dues", "DIRECT", "overdue_list"),
    # overdue amount
    ("what's the total value of unpaid overdue bills", "DIRECT", "overdue_amount"),
    # pending
    ("list the invoices still awaiting payment",   "DIRECT", "pending_list"),
    # revenue
    ("how much money did we make",                 "DIRECT", "total_revenue"),
    ("what were my total sales this period",        "DIRECT", "total_revenue"),
    # invoice count
    ("how many bills are there",                    "DIRECT", "invoice_count"),
    # inventory count
    ("how many distinct products do I stock",       "DIRECT", "inventory_count"),
    # low stock
    ("what items do I need to restock",             "DIRECT", "low_stock"),
    ("which products have almost run out",          "DIRECT", "low_stock"),
    # expiring
    ("which goods will expire shortly",             "DIRECT", "expiring_soon"),
    # top customers / debtors
    ("who buys the most from me",                   "DIRECT", "top_customers"),
    ("which customer has the largest unpaid balance", "DIRECT", "top_debtors"),
    # business summary
    ("give me a quick health check of the business", "DIRECT", "business_summary"),
    # conversational
    ("thanks a lot",                                "CONVERSATIONAL", None),
    ("hey",                                         "CONVERSATIONAL", None),
    # complex
    ("diagnose why my cash flow is tight and suggest fixes", "AI_COMPLEX", None),
    ("build me a plan to recover overdue money over the next month", "AI_COMPLEX", None),
    # simple / writing
    ("write a polite reminder to a late payer",     "AI_SIMPLE", None),
    ("help me phrase a follow up to a client",      "AI_SIMPLE", None),
]


def _run_eval():
    """Classify every eval case once; return (accuracy, report_lines)."""
    router = SemanticRouter()  # real MiniLM encoder
    correct, lines = 0, []
    for query, exp_tier, exp_intent in _EVAL_CASES:
        tier, intent, conf = router.classify(query)
        ok = (tier == exp_tier) and (exp_intent is None or intent == exp_intent)
        correct += int(ok)
        mark = "ok " if ok else "MISS"
        lines.append(f"  [{mark}] '{query}' -> ({tier},{intent},{conf:.2f})"
                     + ("" if ok else f"  expected ({exp_tier},{exp_intent})"))
    return correct / len(_EVAL_CASES), lines


def test_semantic_router_eval_accuracy(capsys):
    pytest.importorskip("sentence_transformers")
    accuracy, lines = _run_eval()

    # Always surface the real number + breakdown (visible with `pytest -s`).
    report = f"\n[intent_router eval] accuracy = {accuracy:.0%} on {len(_EVAL_CASES)} cases\n" + "\n".join(lines)
    with capsys.disabled():
        print(report)

    # Floor only — this is a measuring instrument, not the cutover gate. We read
    # the printed number to decide threshold/seed tuning before wiring it in.
    assert accuracy >= 0.7, report
