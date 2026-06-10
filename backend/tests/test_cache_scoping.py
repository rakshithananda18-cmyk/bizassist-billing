"""
tests/test_cache_scoping.py
===========================
Phase 0 / C4 + C5 regression tests for the in-memory caches.

C4 — invalidating one tenant must NOT evict another tenant's warm cache.
C5 — the query-response cache is LRU-bounded per user (and globally), so memory
     can't grow without limit.
"""
import os
import sys

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, backend_path)

import pytest
import services.context_cache as cc


@pytest.fixture(autouse=True)
def clean_cache():
    cc.invalidate()
    yield
    cc.invalidate()


# ───────────────────────── C4: per-user scoping ─────────────────────────

def test_invalidate_user_cache_only_clears_that_user():
    cc.set_cached_query_response(1, "q", {"response": "A"}, history_salt="saltA")
    cc.set_cached_query_response(2, "q", {"response": "B"}, history_salt="saltB")

    # sanity: both cached
    assert cc.get_cached_query_response(1, "q", "saltA") == {"response": "A"}
    assert cc.get_cached_query_response(2, "q", "saltB") == {"response": "B"}

    # tenant 1 uploads → only tenant 1's cache is busted
    cc.invalidate_user_cache(1)

    assert cc.get_cached_query_response(1, "q", "saltA") is None, "uploader's cache must be cleared"
    assert cc.get_cached_query_response(2, "q", "saltB") == {"response": "B"}, \
        "another tenant's warm cache must survive"


def test_global_invalidate_still_clears_everyone():
    cc.set_cached_query_response(1, "q", {"response": "A"}, history_salt="saltA")
    cc.set_cached_query_response(2, "q", {"response": "B"}, history_salt="saltB")
    cc.invalidate()
    assert cc.get_cached_query_response(1, "q", "saltA") is None
    assert cc.get_cached_query_response(2, "q", "saltB") is None


# ───────────────────────── C5: LRU bounds ─────────────────────────

def test_query_cache_is_bounded_per_user():
    """A single user hammering distinct queries can't grow unbounded."""
    cap = cc.MAX_QUERIES_PER_USER
    for i in range(cap + 50):
        cc.set_cached_query_response(99, f"q{i}", {"response": i}, history_salt=f"salt{i}")
    with cc._lock:
        held = len(cc._query_response_cache.get(99, {}))
    assert held <= cap, f"per-user query cache should cap at {cap}, held {held}"


def test_query_cache_is_bounded_globally():
    """Many one-shot users can't grow the outer cache without limit."""
    cap = cc.MAX_CACHE_USERS
    for uid in range(cap + 50):
        cc.set_cached_query_response(uid, "q", {"response": uid}, history_salt=f"u{uid}")
    with cc._lock:
        held = len(cc._query_response_cache)
    assert held <= cap, f"global query cache should cap at {cap}, held {held}"


def test_lru_evicts_oldest_first():
    """Least-recently-set user is the one evicted when capacity is exceeded."""
    cap = cc.MAX_CACHE_USERS
    # fill to capacity
    for uid in range(cap):
        cc.set_cached_query_response(uid, "q", {"response": uid}, history_salt=f"u{uid}")
    # touch user 0 so it's most-recently-used
    assert cc.get_cached_query_response(0, "q", "u0") == {"response": 0}
    # one more user forces an eviction — user 1 (oldest untouched) should go, not user 0
    cc.set_cached_query_response(cap + 1, "q", {"response": "new"}, history_salt=f"u{cap+1}")
    assert cc.get_cached_query_response(0, "q", "u0") == {"response": 0}, "recently-used user must survive"
    assert cc.get_cached_query_response(1, "q", "u1") is None, "oldest untouched user must be evicted"
