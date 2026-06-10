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
