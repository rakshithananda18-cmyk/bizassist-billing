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
from datetime import date, timedelta
from uuid import uuid4

os.environ["GROQ_API_KEY"] = "mock_key"

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, backend_path)

import pytest
from database.db import engine, SessionLocal
from database.models import Base, Invoice, Inventory, RegisterShift, User
from services.auth import hash_password
from services.intents import resolve_intent, is_intent, INTENT_MAP

@pytest.fixture(scope="module")
def owner_id():
    """Seed a distinct tenant; the suite owns database cleanup."""
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        user = User(username=f"intent_test_user_{uuid4().hex}",
                    password=hash_password("Test123"),
                    business_name="Intent Test Co", role="enterprise")
        db.add(user)
        db.flush()
        business_id = user.id
        db.add(Invoice(business_id=business_id, invoice_id="I-001", customer="Cust A",
                       product="P1", amount=5000, status="Paid",
                       invoice_date="2026-05-01", due_date="2026-05-31"))
        db.add(Invoice(business_id=business_id, invoice_id="I-002", customer="Cust B",
                       product="P2", amount=3000, status="Overdue",
                       invoice_date="2026-04-01", due_date="2026-05-01"))
        db.add(Invoice(business_id=business_id, invoice_id="I-003", customer="Cust A",
                       product="P3", amount=2000, status="Pending",
                       invoice_date="2026-05-15", due_date=(date.today() + timedelta(days=30)).isoformat()))
        db.add(Inventory(business_id=business_id, product_name="Prod X",
                         stock=5, expiry_date=(date.today() + timedelta(days=7)).isoformat(),
                         supplier="Sup 1"))
        db.commit()
        return business_id
    finally:
        db.close()


def test_owner_fixture_preserves_existing_business(monkeypatch):
    """An unrelated tenant at the old fixed ID must survive repeated setup."""
    from sqlalchemy import create_engine, event
    from sqlalchemy.orm import sessionmaker

    isolated_engine = create_engine("sqlite://")

    @event.listens_for(isolated_engine, "connect")
    def enable_foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    isolated_session = sessionmaker(bind=isolated_engine)
    try:
        Base.metadata.create_all(bind=isolated_engine)
        with isolated_session() as db:
            db.add(User(id=88, username="existing_intent_owner", role="enterprise"))
            db.flush()
            shift = RegisterShift(business_id=88, user_id=88)
            db.add(shift)
            db.flush()
            invoice = Invoice(business_id=88, invoice_id="EXISTING", amount=123,
                              shift_id=shift.id)
            db.add(invoice)
            db.commit()
            shift_id, invoice_id = shift.id, invoice.id

        monkeypatch.setattr(f"{__name__}.engine", isolated_engine)
        monkeypatch.setattr(f"{__name__}.SessionLocal", isolated_session)
        first_owner = owner_id.__wrapped__()
        second_owner = owner_id.__wrapped__()

        assert len({88, first_owner, second_owner}) == 3
        with isolated_session() as db:
            assert db.get(User, 88).username == "existing_intent_owner"
            assert db.get(RegisterShift, shift_id).user_id == 88
            assert db.get(Invoice, invoice_id).business_id == 88
            assert db.get(Invoice, invoice_id).amount == 123
    finally:
        isolated_engine.dispose()


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


def test_all_known_intents_return_envelope(owner_id):
    """Every intent in INTENT_MAP must resolve to a valid envelope."""
    skip = {"client_summary"}  # requires params, tested separately
    for intent_key in INTENT_MAP:
        if intent_key in skip:
            continue
        result = resolve_intent(intent_key, owner_id)
        _check_envelope(result)


def test_unknown_intent_returns_none(owner_id):
    assert resolve_intent("totally_unknown_intent", owner_id) is None


def test_is_intent():
    assert is_intent("total_revenue") is True
    assert is_intent("top_debtors") is True
    assert is_intent("fake_thing") is False


# ── top_debtors vs top_customers correctness ─────────────────────────────────

def test_top_debtors_envelope(owner_id):
    result = resolve_intent("top_debtors", owner_id)
    _check_envelope(result)
    md = result["answer"]["markdown"]
    # Must show Cust B (only overdue customer) and their OVERDUE amount (3000)
    assert "Cust B" in md
    assert "3,000" in md
    # Must NOT show Cust A as a debtor (they have no overdue invoices)
    # Cust A total revenue = 7000, but overdue = 0
    assert "Cust A" not in md


def test_top_customers_envelope(owner_id):
    result = resolve_intent("top_customers", owner_id)
    _check_envelope(result)
    md = result["answer"]["markdown"]
    # Cust A total revenue = 5000 + 2000 = 7000 (highest)
    assert "Cust A" in md
    assert "7,000" in md


def test_top_debtors_title(owner_id):
    result = resolve_intent("top_debtors", owner_id)
    assert "Debtor" in result["answer"]["title"] or "Outstanding" in result["answer"]["title"]


def test_top_customers_title(owner_id):
    result = resolve_intent("top_customers", owner_id)
    assert "Customer" in result["answer"]["title"]


# ── Suggestions are typed correctly ──────────────────────────────────────────

def test_suggestions_have_valid_types(owner_id):
    result = resolve_intent("overdue_list", owner_id)
    for s in result["suggestions"]:
        assert s["type"] in ("deterministic", "ai", "action", "select")
        assert "label" in s
        assert "id" in s


def test_overdue_list_has_send_reminders(owner_id):
    """Overdue list must always offer a reminder action when overdue exist."""
    result = resolve_intent("overdue_list", owner_id)
    types = {s["type"] for s in result["suggestions"]}
    # Must have at least one action or select type (send_reminders)
    assert "action" in types or "select" in types


def test_client_summary_with_params(owner_id):
    result = resolve_intent("client_summary", owner_id, params={"customer": "Cust A"})
    _check_envelope(result)
    assert "Cust A" in result["answer"]["markdown"]


def test_suggestions_capped_at_4(owner_id):
    for intent_key in INTENT_MAP:
        result = resolve_intent(intent_key, owner_id)
        if result:
            assert len(result["suggestions"]) <= 4, f"{intent_key} returned >4 suggestions"
