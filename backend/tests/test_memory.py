"""
tests/test_memory.py
====================
Phase 4 — Unit tests for memory_service.

Tests:
  T1. distill_memory() calls Groq, parses JSON, writes BusinessFact rows.
  T2. distill_memory() handles malformed JSON gracefully.
  T3. get_business_facts() returns formatted bullets for existing facts.
  T4. get_business_facts() returns empty string when no facts exist.
  T5. get_business_snapshot() includes [Durable Business Memories] section.
"""

import json
import pytest
from unittest.mock import patch, MagicMock
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# ── Test DB setup ────────────────────────────────────────────────────────────
import os
import sys
backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, backend_path)

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_bizassist.db")
os.environ.setdefault("GROQ_API_KEY", "test-key")

import services.memory_service
from database.db import Base
from database.models import BusinessFact

engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
Base.metadata.create_all(engine)
TestSession = sessionmaker(bind=engine)


def _make_groq_response(facts: list) -> MagicMock:
    """Build a mock Groq chat completion response containing a JSON fact list."""
    mock_choice = MagicMock()
    mock_choice.message.content = json.dumps({"facts": facts})
    mock_resp = MagicMock()
    mock_resp.choices = [mock_choice]
    return mock_resp


# ── T1: distill_memory writes facts to DB ───────────────────────────────────
def test_distill_memory_writes_facts(monkeypatch, tmp_path):
    """distill_memory should extract facts and upsert into BusinessFact table."""
    sample_facts = [
        {
            "fact_key": "late_payer_abc",
            "category": "payment_delay",
            "fact_text": "ABC consistently pays 30 days late.",
            "confidence": 0.9,
        },
        {
            "fact_key": "q4_revenue_spike",
            "category": "sales_pattern",
            "fact_text": "Revenue spikes 40% in Q4.",
            "confidence": 0.8,
        },
    ]

    mock_resp = _make_groq_response(sample_facts)

    with patch("services.memory_service.SessionLocal", return_value=TestSession()), \
         patch("services.memory_service._groq") as mock_groq:
        mock_groq.chat.completions.create.return_value = mock_resp

        from services.memory_service import distill_memory
        distill_memory(business_id=1)

    db = TestSession()
    facts = db.query(BusinessFact).filter(BusinessFact.business_id == 1).all()
    db.close()

    assert len(facts) == 2
    keys = {f.fact_key for f in facts}
    assert "late_payer_abc" in keys
    assert "q4_revenue_spike" in keys


# ── T2: distill_memory handles bad JSON gracefully ───────────────────────────
def test_distill_memory_bad_json(monkeypatch):
    """distill_memory should not raise on malformed LLM output."""
    mock_choice = MagicMock()
    mock_choice.message.content = "not valid json!!!"
    mock_resp = MagicMock()
    mock_resp.choices = [mock_choice]

    with patch("services.memory_service.SessionLocal", return_value=TestSession()), \
         patch("services.memory_service._groq") as mock_groq:
        mock_groq.chat.completions.create.return_value = mock_resp

        from services.memory_service import distill_memory
        # Should not raise
        distill_memory(business_id=99)


# ── T3: get_business_facts returns bullet list ───────────────────────────────
def test_get_business_facts_returns_bullets():
    db = TestSession()
    db.add(BusinessFact(
        business_id=2,
        fact_key="test_fact",
        category="cash_flow",
        fact_text="Collection rate below 60% for 3 months.",
        confidence=0.85,
    ))
    db.commit()
    db.close()

    with patch("services.memory_service.SessionLocal", return_value=TestSession()):
        from services.memory_service import get_business_facts
        result = get_business_facts(business_id=2)

    assert "[Durable Business Memories]" in result
    assert "Collection rate below 60%" in result


# ── T4: get_business_facts returns empty string when no facts ────────────────
def test_get_business_facts_empty():
    with patch("services.memory_service.SessionLocal", return_value=TestSession()):
        from services.memory_service import get_business_facts
        result = get_business_facts(business_id=9999)

    assert result == ""


# ── T5: get_business_snapshot includes memory section ────────────────────────
def test_snapshot_includes_memory(monkeypatch):
    """get_business_snapshot should append [Durable Business Memories] when facts exist."""
    with patch("services.memory_service.get_business_facts", return_value="[Durable Business Memories]\n  • [cash_flow] Test fact."), \
         patch("services.recommendations.SessionLocal", return_value=TestSession()):
        from services.recommendations import get_business_snapshot
        snapshot = get_business_snapshot(user_id=2)

    assert "[Durable Business Memories]" in snapshot
