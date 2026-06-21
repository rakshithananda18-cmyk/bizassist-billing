"""
test_intents.py
===============
Tests the full resolve_intent() call — the public interface between
routes/intents.py and services/intents.py.

Verifies:
- The returned envelope shape: {answer, source, suggestions, meta}
- Intent-to-handler mapping is correct (especially top_debtors ≠ top_customers)
- Unknown intent returns None
- Suggestions are attached and typed correctly

Run:  pytest tests/test_intents.py -v
"""
import os
import sys

os.environ["DATABASE_URL"] = "sqlite:///./test_intents.db"
os.environ["GROQ_API_KEY"] = "mock_key"

for db_path in ["test_intents.db"]:
    if os.path.exists(db_path):
        try:
            os.remove(db_path)
        except Exception:
            pass

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, backend_path)

import pytest
from database.db import engine, SessionLocal
from database.models import Base, Invoice, Inventory, User
from services.auth import hash_password
from services.intents import resolve_intent, is_intent, INTENT_MAP

USER_ID = 88

@pytest.fixture(scope="session", autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        db.query(User).filter(User.id == USER_ID).delete()
        db.query(Invoice).filter(Invoice.business_id == USER_ID).delete()
        db.query(Inventory).filter(Inventory.business_id == USER_ID).delete()
        db.commit()
        db.add(User(id=USER_ID, username="intent_test_user",
                    password=hash_password("Test123"),
                    business_name="Intent Test Co", role="enterprise"))
        db.add(Invoice(business_id=USER_ID, invoice_id="I-001", customer="Cust A",
                       product="P1", amount=5000, status="Paid",
                       invoice_date="2026-05-01", due_date="2026-05-31"))
        db.add(Invoice(business_id=USER_ID, invoice_id="I-002", customer="Cust B",
                       product="P2", amount=3000, status="Overdue",
                       invoice_date="2026-04-01", due_date="2026-05-01"))
        db.add(Invoice(business_id=USER_ID, invoice_id="I-003", customer="Cust A",
                       product="P3", amount=2000, status="Pending",
                       invoice_date="2026-05-15", due_date="2026-06-30"))
        db.add(Inventory(business_id=USER_ID, product_name="Prod X",
                         stock=5, expiry_date="2026-06-15", supplier="Sup 1"))
        db.commit()
    finally:
        db.close()
    yield
    for db_path in ["test_intents.db"]:
        if os.path.exists(db_path):
            try:
                os.remove(db_path)
            except Exception:
                pass


# ── Envelope shape ────────────────────────────────────────────────────────────

def _check_envelope(result):
    """Every resolve_intent() must return the standard envelope."""
    assert result is not None, "resolve_intent returned None for a known intent"
    assert "answer" in result
    assert "markdown" in result["answer"]
    assert len(result["answer"]["markdown"]) > 0
    assert "source" in result
    assert result["source"] == "db"
    assert "suggestions" in result
    assert isinstance(result["suggestions"], list)
    assert "meta" in result


def test_all_known_intents_return_envelope():
    """Every intent in INTENT_MAP must resolve to a valid envelope."""
    skip = {"client_summary"}  # requires params, tested separately
    for intent_key in INTENT_MAP:
        if intent_key in skip:
            continue
        result = resolve_intent(intent_key, USER_ID)
        _check_envelope(result)


def test_unknown_intent_returns_none():
    assert resolve_intent("totally_unknown_intent", USER_ID) is None


def test_is_intent():
    assert is_intent("total_revenue") is True
    assert is_intent("top_debtors") is True
    assert is_intent("fake_thing") is False


# ── top_debtors vs top_customers correctness ─────────────────────────────────

def test_top_debtors_envelope():
    result = resolve_intent("top_debtors", USER_ID)
    _check_envelope(result)
    md = result["answer"]["markdown"]
    # Must show Cust B (only overdue customer) and their OVERDUE amount (3000)
    assert "Cust B" in md
    assert "3,000" in md
    # Must NOT show Cust A as a debtor (they have no overdue invoices)
    # Cust A total revenue = 7000, but overdue = 0
    assert "Cust A" not in md


def test_top_customers_envelope():
    result = resolve_intent("top_customers", USER_ID)
    _check_envelope(result)
    md = result["answer"]["markdown"]
    # Cust A total revenue = 5000 + 2000 = 7000 (highest)
    assert "Cust A" in md
    assert "7,000" in md


def test_top_debtors_title():
    result = resolve_intent("top_debtors", USER_ID)
    assert "Debtor" in result["answer"]["title"] or "Outstanding" in result["answer"]["title"]


def test_top_customers_title():
    result = resolve_intent("top_customers", USER_ID)
    assert "Customer" in result["answer"]["title"]


# ── Suggestions are typed correctly ──────────────────────────────────────────

def test_suggestions_have_valid_types():
    result = resolve_intent("overdue_list", USER_ID)
    for s in result["suggestions"]:
        assert s["type"] in ("deterministic", "ai", "action", "select")
        assert "label" in s
        assert "id" in s


def test_overdue_list_has_send_reminders():
    """Overdue list must always offer a reminder action when overdue exist."""
    result = resolve_intent("overdue_list", USER_ID)
    types = {s["type"] for s in result["suggestions"]}
    # Must have at least one action or select type (send_reminders)
    assert "action" in types or "select" in types


def test_client_summary_with_params():
    result = resolve_intent("client_summary", USER_ID, params={"customer": "Cust A"})
    _check_envelope(result)
    assert "Cust A" in result["answer"]["markdown"]


def test_suggestions_capped_at_4():
    for intent_key in INTENT_MAP:
        result = resolve_intent(intent_key, USER_ID)
        if result:
            assert len(result["suggestions"]) <= 4, f"{intent_key} returned >4 suggestions"
