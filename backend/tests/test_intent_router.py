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
    # invoice_count
    ("how many invoices do I have", "DIRECT", "invoice_count"),
    ("invoice count", "DIRECT", "invoice_count"),
    ("total invoices", "DIRECT", "invoice_count"),
    ("how many bills are there", "DIRECT", "invoice_count"),
    ("number of invoices", "DIRECT", "invoice_count"),
    ("count of invoices", "DIRECT", "invoice_count"),
    ("how many bills", "DIRECT", "invoice_count"),
    ("what is my total invoice count", "DIRECT", "invoice_count"),
    ("how many client invoices exist", "DIRECT", "invoice_count"),
    ("how many bills in database", "DIRECT", "invoice_count"),

    # total_revenue
    ("what is my total revenue", "DIRECT", "total_revenue"),
    ("total sales", "DIRECT", "total_revenue"),
    ("how much revenue", "DIRECT", "total_revenue"),
    ("revenue so far", "DIRECT", "total_revenue"),
    ("total turnover", "DIRECT", "total_revenue"),
    ("how much have I earned", "DIRECT", "total_revenue"),
    ("what's my income", "DIRECT", "total_revenue"),
    ("total revenue this year", "DIRECT", "total_revenue"),
    ("how much money did we make", "DIRECT", "total_revenue"),
    ("what were my total sales this period", "DIRECT", "total_revenue"),

    # revenue_month_detail
    ("revenue in March 2026", "DIRECT", "revenue_month_detail"),
    ("sales for January", "DIRECT", "revenue_month_detail"),
    ("income in Feb", "DIRECT", "revenue_month_detail"),
    ("how much did we sell in December 2025", "DIRECT", "revenue_month_detail"),
    ("revenue month-wise for October", "DIRECT", "revenue_month_detail"),
    ("sales overview for April", "DIRECT", "revenue_month_detail"),

    # overdue_list
    ("show overdue invoices", "DIRECT", "overdue_list"),
    ("who hasn't paid me", "DIRECT", "overdue_list"),
    ("who owes me money", "DIRECT", "overdue_list"),
    ("list overdue customers", "DIRECT", "overdue_list"),
    ("outstanding payments", "DIRECT", "overdue_list"),
    ("show me my debtors", "DIRECT", "overdue_list"),
    ("what's overdue", "DIRECT", "overdue_list"),
    ("customers who still owe me", "DIRECT", "overdue_list"),
    ("unpaid overdue accounts", "DIRECT", "overdue_list"),
    ("what's my collection situation", "DIRECT", "overdue_list"),
    ("show me everyone who is behind on payments", "DIRECT", "overdue_list"),
    ("which clients still haven't cleared their dues", "DIRECT", "overdue_list"),
    ("who is overdue", "DIRECT", "overdue_list"),
    ("list overdue", "DIRECT", "overdue_list"),
    ("overdue people only top 15", "DIRECT", "overdue_list"),
    ("what's outstanding from clients", "DIRECT", "overdue_list"),
    ("outstanding from clients", "DIRECT", "overdue_list"),

    # overdue_amount
    ("how much is overdue", "DIRECT", "overdue_amount"),
    ("total overdue amount", "DIRECT", "overdue_amount"),
    ("total outstanding amount", "DIRECT", "overdue_amount"),
    ("how much money is overdue", "DIRECT", "overdue_amount"),
    ("value of overdue invoices", "DIRECT", "overdue_amount"),
    ("what's the total value of unpaid overdue bills", "DIRECT", "overdue_amount"),
    ("what is the total amount overdue", "DIRECT", "overdue_amount"),
    ("how much money is outstanding", "DIRECT", "overdue_amount"),

    # overdue_range_detail
    ("overdue in range 30-60 days", "DIRECT", "overdue_range_detail"),
    ("outstanding invoices 90+ days", "DIRECT", "overdue_range_detail"),
    ("overdue payments 61-90 days", "DIRECT", "overdue_range_detail"),
    ("bills overdue for more than 90 days", "DIRECT", "overdue_range_detail"),
    ("list overdue invoices older than 60 days", "DIRECT", "overdue_range_detail"),

    # pending_list
    ("show pending invoices", "DIRECT", "pending_list"),
    ("list pending payments", "DIRECT", "pending_list"),
    ("unpaid invoices", "DIRECT", "pending_list"),
    ("what's pending", "DIRECT", "pending_list"),
    ("invoices not yet paid", "DIRECT", "pending_list"),
    ("awaiting payment", "DIRECT", "pending_list"),
    ("list the invoices still awaiting payment", "DIRECT", "pending_list"),
    ("pending payment", "DIRECT", "pending_list"),
    ("not paid", "DIRECT", "pending_list"),
    ("unpaid invoices list", "DIRECT", "pending_list"),

    # top_customers
    ("top customers", "DIRECT", "top_customers"),
    ("best customers", "DIRECT", "top_customers"),
    ("highest paying customers", "DIRECT", "top_customers"),
    ("biggest buyers", "DIRECT", "top_customers"),
    ("who are my biggest customers", "DIRECT", "top_customers"),
    ("most valuable clients", "DIRECT", "top_customers"),
    ("who spends the most with me", "DIRECT", "top_customers"),
    ("customers by purchase volume", "DIRECT", "top_customers"),
    ("my biggest spenders", "DIRECT", "top_customers"),
    ("who purchases the most", "DIRECT", "top_customers"),
    ("who buys the most from me", "DIRECT", "top_customers"),

    # top_debtors
    ("top debtors", "DIRECT", "top_debtors"),
    ("who owes me the most", "DIRECT", "top_debtors"),
    ("biggest debtor", "DIRECT", "top_debtors"),
    ("largest outstanding customer", "DIRECT", "top_debtors"),
    ("worst paying customers", "DIRECT", "top_debtors"),
    ("which customer has the largest unpaid balance", "DIRECT", "top_debtors"),
    ("who owes the most money", "DIRECT", "top_debtors"),

    # inventory_count
    ("how many products", "DIRECT", "inventory_count"),
    ("inventory count", "DIRECT", "inventory_count"),
    ("stock count", "DIRECT", "inventory_count"),
    ("number of items in stock", "DIRECT", "inventory_count"),
    ("how many SKUs", "DIRECT", "inventory_count"),
    ("total products", "DIRECT", "inventory_count"),
    ("how many distinct products do I stock", "DIRECT", "inventory_count"),
    ("how many items in inventory", "DIRECT", "inventory_count"),

    # low_stock
    ("low stock items", "DIRECT", "low_stock"),
    ("what's running low", "DIRECT", "low_stock"),
    ("out of stock", "DIRECT", "low_stock"),
    ("items to reorder", "DIRECT", "low_stock"),
    ("which products are almost out", "DIRECT", "low_stock"),
    ("what should I restock", "DIRECT", "low_stock"),
    ("what items do I need to restock", "DIRECT", "low_stock"),
    ("low stock", "DIRECT", "low_stock"),

    # expiring_soon
    ("expiring products", "DIRECT", "expiring_soon"),
    ("items about to expire", "DIRECT", "expiring_soon"),
    ("what's expiring soon", "DIRECT", "expiring_soon"),
    ("near expiry stock", "DIRECT", "expiring_soon"),
    ("products expiring this month", "DIRECT", "expiring_soon"),
    ("stock close to expiry", "DIRECT", "expiring_soon"),
    ("which goods will expire shortly", "DIRECT", "expiring_soon"),
    ("expiring soon", "DIRECT", "expiring_soon"),

    # business_summary
    ("business summary", "DIRECT", "business_summary"),
    ("give me an overview", "DIRECT", "business_summary"),
    ("dashboard snapshot", "DIRECT", "business_summary"),
    ("how's my business doing", "DIRECT", "business_summary"),
    ("business health", "DIRECT", "business_summary"),
    ("quick snapshot of my business", "DIRECT", "business_summary"),
    ("is my business doing well", "DIRECT", "business_summary"),
    ("business health check", "DIRECT", "business_summary"),
    ("how is the business performing overall", "DIRECT", "business_summary"),
    ("give me the key numbers at a glance", "DIRECT", "business_summary"),
    ("give me a quick health check of the business", "DIRECT", "business_summary"),

    # client_summary
    ("tell me about this customer", "DIRECT", "client_summary"),
    ("do you know this client", "DIRECT", "client_summary"),
    ("details about a customer", "DIRECT", "client_summary"),
    ("customer profile", "DIRECT", "client_summary"),
    ("what's the status of a client", "DIRECT", "client_summary"),
    ("info on a buyer", "DIRECT", "client_summary"),
    ("do you know srinivas kirana", "DIRECT", "client_summary"),
    ("tell me about nilgiris fresh", "DIRECT", "client_summary"),
    ("do you know Rajesh Traders", "DIRECT", "client_summary"),
    ("tell me about Sharma Stores", "DIRECT", "client_summary"),
    ("info on Patel Kirana", "DIRECT", "client_summary"),
    ("what's the status of Krishna Enterprises", "DIRECT", "client_summary"),

    # conversational
    ("hi", "CONVERSATIONAL", None),
    ("hello", "CONVERSATIONAL", None),
    ("hey there", "CONVERSATIONAL", None),
    ("thanks", "CONVERSATIONAL", None),
    ("thank you", "CONVERSATIONAL", None),
    ("okay got it", "CONVERSATIONAL", None),
    ("great", "CONVERSATIONAL", None),
    ("cool", "CONVERSATIONAL", None),
    ("bye", "CONVERSATIONAL", None),
    ("sounds good", "CONVERSATIONAL", None),
    ("noted", "CONVERSATIONAL", None),
    ("perfect", "CONVERSATIONAL", None),
    ("thanks a lot", "CONVERSATIONAL", None),
    ("hey", "CONVERSATIONAL", None),

    # ai_simple
    ("draft a payment reminder message", "AI_SIMPLE", None),
    ("write a message to a customer", "AI_SIMPLE", None),
    ("which customer should I call first", "AI_SIMPLE", None),
    ("explain my cash flow situation", "AI_SIMPLE", None),
    ("what payment terms should I offer", "AI_SIMPLE", None),
    ("help me write a follow-up email", "AI_SIMPLE", None),
    ("compose a thank you note to a client", "AI_SIMPLE", None),
    ("write a polite reminder to a late payer", "AI_SIMPLE", None),
    ("help me phrase a follow up to a client", "AI_SIMPLE", None),

    # ai_complex
    ("analyse my business and give me a recovery plan", "AI_COMPLEX", None),
    ("why is my collection rate low and how do I fix it", "AI_COMPLEX", None),
    ("give me a recovery strategy for overdue accounts", "AI_COMPLEX", None),
    ("compare my revenue trends and give insights", "AI_COMPLEX", None),
    ("what should I do to improve my profitability", "AI_COMPLEX", None),
    ("what are the root causes of my overdue problem", "AI_COMPLEX", None),
    ("create a 30 day collection plan", "AI_COMPLEX", None),
    ("do a deep dive analysis of my business with recommendations", "AI_COMPLEX", None),
    ("diagnose my cash flow problems and recommend fixes", "AI_COMPLEX", None),
    ("what is causing my poor collections and how do I fix it", "AI_COMPLEX", None),
    ("figure out why money is tight and suggest a plan", "AI_COMPLEX", None),
    ("diagnose why my cash flow is tight and suggest fixes", "AI_COMPLEX", None),
    ("build me a plan to recover overdue money over the next month", "AI_COMPLEX", None),
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
    assert accuracy >= 0.95, report
