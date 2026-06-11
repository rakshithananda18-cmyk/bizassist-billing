"""
tests/test_cache_salt.py
========================
Phase 0 / C6 — the query-cache salt is date-keyed, so day-sensitive answers
("days overdue", "expiring soon", "today's priorities") get a fresh cache each
day instead of being served stale across a day boundary.
"""
import os
import sys

os.environ["DATABASE_URL"] = "sqlite:///./test_bizassist.db"
os.environ["GROQ_API_KEY"] = "mock_groq_api_key"

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, backend_path)

import pytest
from services.ai_router import _cache_salt


def test_same_inputs_same_day_is_a_hit():
    a = _cache_salt(1, "AI_SIMPLE", "show overdue", "overdue_list", day="2026-01-15")
    b = _cache_salt(1, "AI_SIMPLE", "who owes me", "overdue_list", day="2026-01-15")
    # same user + same topic + same day => same salt (semantic variants share a hit)
    assert a == b


def test_different_day_is_a_miss():
    d1 = _cache_salt(1, "AI_SIMPLE", "show overdue", "overdue_list", day="2026-01-15")
    d2 = _cache_salt(1, "AI_SIMPLE", "show overdue", "overdue_list", day="2026-01-16")
    assert d1 != d2, "a new day must produce a different cache key"


def test_scoped_per_user():
    u1 = _cache_salt(1, "AI_SIMPLE", "show overdue", "overdue_list", day="2026-01-15")
    u2 = _cache_salt(2, "AI_SIMPLE", "show overdue", "overdue_list", day="2026-01-15")
    assert u1 != u2


def test_complex_keys_on_exact_query():
    # AI_COMPLEX keys on the exact query, not the topic
    q1 = _cache_salt(1, "AI_COMPLEX", "analyse my Q1 cash flow", "total_revenue", day="2026-01-15")
    q2 = _cache_salt(1, "AI_COMPLEX", "analyse my Q2 cash flow", "total_revenue", day="2026-01-15")
    assert q1 != q2


def test_defaults_to_today_when_day_omitted():
    # omitting day uses today's date and is stable within a call pair
    a = _cache_salt(1, "AI_SIMPLE", "show overdue", "overdue_list")
    b = _cache_salt(1, "AI_SIMPLE", "who owes me", "overdue_list")
    assert a == b


# ── DIRECT handler precision (the "total revenue → invoice count" bug) ──

def test_direct_handlers_with_same_topic_do_not_collide():
    # _detect_topic maps BOTH to 'total_revenue', but they're different intents
    # and must NOT share a cache entry.
    invoices = _cache_salt(1, "DIRECT", "how many invoices", "total_revenue",
                           handler_key="invoice_count", day="2026-01-15")
    revenue  = _cache_salt(1, "DIRECT", "total revenue", "total_revenue",
                           handler_key="total_revenue", day="2026-01-15")
    assert invoices != revenue


def test_top_debtors_does_not_collide_with_overdue_list():
    # 'who owes me the most' (top_debtors) vs 'show overdue' (overdue_list) —
    # _detect_topic lumps both as 'overdue_list'.
    debtors = _cache_salt(1, "DIRECT", "who owes me the most", "overdue_list",
                          handler_key="top_debtors", day="2026-01-15")
    overdue = _cache_salt(1, "DIRECT", "show overdue invoices", "overdue_list",
                          handler_key="overdue_list", day="2026-01-15")
    assert debtors != overdue


def test_direct_and_promoted_variant_share_when_same_intent():
    # DIRECT overdue and a semantic variant promoted to the same intent SHOULD share.
    direct   = _cache_salt(1, "DIRECT", "show overdue", "overdue_list",
                           handler_key="overdue_list", day="2026-01-15")
    promoted = _cache_salt(1, "AI_SIMPLE", "who owes me money", "overdue_list",
                           handler_key=None, day="2026-01-15")
    assert direct == promoted


def test_client_summary_keyed_on_query_per_customer():
    # different customers (and a non-existent one) must NOT share a cache entry,
    # otherwise the first looked-up customer is returned for everyone.
    a = _cache_salt(1, "DIRECT", "do you know namdhari fresh", "business_summary",
                    handler_key="client_summary", day="2026-01-15")
    b = _cache_salt(1, "DIRECT", "tell me about star bazaar", "business_summary",
                    handler_key="client_summary", day="2026-01-15")
    c = _cache_salt(1, "DIRECT", "tell me about zxqwerty fictional", "business_summary",
                    handler_key="client_summary", day="2026-01-15")
    assert a != b and a != c and b != c


def test_writing_task_keyed_on_query_not_topic():
    # 'draft a reminder for overdue customers' must NOT share the overdue data cache.
    writing = _cache_salt(1, "AI_SIMPLE", "draft a reminder for overdue customers",
                          "overdue_list", handler_key=None, is_writing=True, day="2026-01-15")
    data    = _cache_salt(1, "DIRECT", "show overdue", "overdue_list",
                          handler_key="overdue_list", day="2026-01-15")
    assert writing != data
