"""
tests/test_feedback.py
======================
The answer-quality feedback loop: a thumbs-down that names the right intent
creates a per-query override, so re-running the SAME query routes correctly.
Up-votes and guidance-less down-votes log but never override.
"""
import os
import sys

os.environ["DATABASE_URL"] = "sqlite:///./test_bizassist.db"
os.environ["GROQ_API_KEY"] = "mock_groq_api_key"

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, backend_path)

import pytest
from database.db import SessionLocal
from database.models import Base, AIFeedback, AIQueryOverride
from services.feedback_service import record_feedback, get_override, normalize_query

BID = 778899


def _ensure_schema():
    db = SessionLocal()
    try:
        Base.metadata.create_all(bind=db.get_bind())
    finally:
        db.close()


def _clear():
    db = SessionLocal()
    try:
        db.query(AIFeedback).filter(AIFeedback.business_id == BID).delete()
        db.query(AIQueryOverride).filter(AIQueryOverride.business_id == BID).delete()
        db.commit()
    finally:
        db.close()


@pytest.fixture(autouse=True)
def _setup():
    _ensure_schema()
    _clear()
    yield
    _clear()


def test_normalize_query_lowercases_and_collapses_space():
    assert normalize_query("  Tell  ME  about  X ") == "tell me about x"


def test_downvote_with_correction_creates_override():
    r = record_feedback(BID, session_id="s", query="show me lakshmi",
                        route="DIRECT", handler_key="overdue_list",
                        verdict="down", correction="client_summary")
    assert r["ok"] and r["override"]
    assert get_override(BID, "show me lakshmi") == ("DIRECT", "client_summary")
    # normalization: different spacing/case still hits the same override
    assert get_override(BID, "  Show Me  Lakshmi ") == ("DIRECT", "client_summary")


def test_upvote_creates_no_override():
    r = record_feedback(BID, session_id="s", query="total revenue",
                        route="DIRECT", handler_key="total_revenue", verdict="up")
    assert r["ok"] and not r["override"]
    assert get_override(BID, "total revenue") is None


def test_downvote_without_correction_logs_only():
    r = record_feedback(BID, session_id="s", query="weird query",
                        route="AI_SIMPLE", handler_key=None, verdict="down")
    assert r["ok"] and not r["override"]
    assert get_override(BID, "weird query") is None


def test_override_is_upserted_not_duplicated():
    record_feedback(BID, session_id="s", query="q", route="DIRECT",
                    handler_key="overdue_list", verdict="down", correction="client_summary")
    record_feedback(BID, session_id="s", query="q", route="DIRECT",
                    handler_key="overdue_list", verdict="down", correction="total_revenue")
    assert get_override(BID, "q") == ("DIRECT", "total_revenue")
    db = SessionLocal()
    try:
        n = (db.query(AIQueryOverride)
             .filter(AIQueryOverride.business_id == BID, AIQueryOverride.query_norm == "q")
             .count())
        assert n == 1, "correction must upsert, not stack duplicate overrides"
    finally:
        db.close()


def test_tier_correction_maps_to_route_without_handler():
    record_feedback(BID, session_id="s", query="deep one", route="AI_SIMPLE",
                    handler_key=None, verdict="down", correction="ai_complex")
    assert get_override(BID, "deep one") == ("AI_COMPLEX", None)


def test_invalid_verdict_rejected():
    assert record_feedback(BID, session_id="s", query="q", route="DIRECT",
                           handler_key="x", verdict="maybe")["ok"] is False


def test_unknown_correction_rejected():
    r = record_feedback(BID, session_id="s", query="q", route="DIRECT",
                        handler_key="x", verdict="down", correction="nonsense")
    assert r["ok"] is False
    assert get_override(BID, "q") is None
