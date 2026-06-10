"""
tests/test_rate_limiter.py
==========================
Phase 0 / H4 — daily usage is computed with a SQL aggregate, not by loading
every TokenUsage row into Python. This test pins the aggregate's correctness:
counts today only, this business only, and sums tokens / complex counts right.
"""
import os
import sys
from datetime import datetime, timedelta

os.environ["DATABASE_URL"] = "sqlite:///./test_bizassist.db"
os.environ["GROQ_API_KEY"] = "mock_groq_api_key"

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, backend_path)

import pytest
import services.rate_limiter as rl
from database.db import SessionLocal
from database.models import Base, TokenUsage

BID = 987654   # an id unlikely to collide with seeded/test users


def _ensure_schema():
    """
    Create the schema on the engine SessionLocal is *actually* bound to, at run
    time. Test modules juggle DATABASE_URL / delete db files at import, but the
    process shares one module-level engine — so we (re)create tables against the
    live bind right before using them, rather than trusting import-time state.
    """
    db = SessionLocal()
    try:
        Base.metadata.create_all(bind=db.get_bind())
    finally:
        db.close()


def _clear():
    db = SessionLocal()
    try:
        db.query(TokenUsage).filter(TokenUsage.business_id == BID).delete()
        db.commit()
    finally:
        db.close()


@pytest.fixture(autouse=True)
def clean():
    _ensure_schema()
    _clear()
    yield
    _clear()


def _add(rows):
    db = SessionLocal()
    try:
        db.add_all(rows)
        db.commit()
    finally:
        db.close()


def test_today_usage_aggregate_counts_and_sums():
    now = datetime.utcnow()
    _add([
        TokenUsage(business_id=BID, model="m", model_tier="AI_SIMPLE",
                   input_tokens=100, output_tokens=50, total_tokens=150, timestamp=now),
        TokenUsage(business_id=BID, model="m", model_tier="AI_COMPLEX",
                   input_tokens=200, output_tokens=100, total_tokens=300, timestamp=now),
        TokenUsage(business_id=BID, model="m", model_tier="AI_COMPLEX",
                   input_tokens=10, output_tokens=5, total_tokens=15, timestamp=now),
        # 2 days ago — must be excluded from "today"
        TokenUsage(business_id=BID, model="m", model_tier="AI_SIMPLE",
                   input_tokens=999, output_tokens=999, total_tokens=9999,
                   timestamp=now - timedelta(days=2)),
    ])

    usage = rl._get_today_usage(BID)
    assert usage["queries_today"] == 3, "yesterday's row must be excluded"
    assert usage["tokens_today"] == 465, "sum of today's total_tokens (150+300+15)"
    assert usage["complex_today"] == 2, "only AI_COMPLEX rows counted"


def test_today_usage_empty_is_zeroed():
    usage = rl._get_today_usage(BID)
    assert usage == {"queries_today": 0, "tokens_today": 0, "complex_today": 0}


def test_today_usage_is_scoped_to_business():
    now = datetime.utcnow()
    _add([
        TokenUsage(business_id=BID, model="m", model_tier="AI_SIMPLE",
                   input_tokens=1, output_tokens=1, total_tokens=2, timestamp=now),
        # a different business — must not leak into BID's totals
        TokenUsage(business_id=BID + 1, model="m", model_tier="AI_COMPLEX",
                   input_tokens=500, output_tokens=500, total_tokens=1000, timestamp=now),
    ])
    try:
        usage = rl._get_today_usage(BID)
        assert usage["queries_today"] == 1
        assert usage["tokens_today"] == 2
        assert usage["complex_today"] == 0
    finally:
        db = SessionLocal()
        try:
            db.query(TokenUsage).filter(TokenUsage.business_id == BID + 1).delete()
            db.commit()
        finally:
            db.close()
