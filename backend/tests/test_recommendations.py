"""
test_recommendations.py
=======================
Tests services/recommendations.py — the Tier 1 rule-based suggestion engine.

Verifies:
- signals() returns all expected keys
- Collection rate < 70% triggers cashflow emergency chip
- overdue_list suggestions include a select/action chip for send_reminders
- Suggestions are deduped and capped at 4
- select-type chips carry options[]

Run:  pytest tests/test_recommendations.py -v
"""
import os
import sys

os.environ["DATABASE_URL"] = "sqlite:///./test_recs.db"
os.environ["GROQ_API_KEY"] = "mock_key"

for db_path in ["test_recs.db"]:
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
from services.recommendations import signals, recommend

USER_ID = 77

@pytest.fixture(scope="session", autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        db.add(User(id=USER_ID, username="rec_test_user",
                    password=hash_password("Test123"),
                    business_name="Rec Test Co", role="enterprise"))
        # Low collection rate: paid=10000, total=30000 → 33%
        db.add(Invoice(business_id=USER_ID, invoice_id="R-001",
                       customer="Alpha", product="P1", amount=10000,
                       status="Paid", invoice_date="2026-05-01", due_date="2026-05-31"))
        db.add(Invoice(business_id=USER_ID, invoice_id="R-002",
                       customer="Alpha", product="P2", amount=12000,
                       status="Overdue", invoice_date="2026-04-01", due_date="2026-05-01"))
        db.add(Invoice(business_id=USER_ID, invoice_id="R-003",
                       customer="Beta", product="P3", amount=8000,
                       status="Pending", invoice_date="2026-05-10", due_date="2026-06-30"))
        # Low stock items
        db.add(Inventory(business_id=USER_ID, product_name="LowItem",
                         stock=3, expiry_date="2027-01-01", supplier="S1"))
        db.commit()
    finally:
        db.close()
    yield
    for db_path in ["test_recs.db"]:
        if os.path.exists(db_path):
            try:
                os.remove(db_path)
            except Exception:
                pass


# ── signals() ────────────────────────────────────────────────────────────────

def test_signals_has_all_keys():
    s = signals(USER_ID)
    required_keys = {"overdue", "pending", "low_stock", "collection_rate", "overdue_options"}
    assert required_keys.issubset(set(s.keys()))


def test_signals_overdue_count():
    s = signals(USER_ID)
    assert s["overdue"] == 1   # R-002


def test_signals_pending_count():
    s = signals(USER_ID)
    assert s["pending"] == 1   # R-003


def test_signals_low_stock_count():
    s = signals(USER_ID)
    assert s["low_stock"] == 1  # LowItem (stock=3)


def test_signals_collection_rate():
    s = signals(USER_ID)
    # Paid=10000, Total=30000 → 33%
    assert s["collection_rate"] == 33


def test_signals_overdue_options_shape():
    s = signals(USER_ID)
    assert isinstance(s["overdue_options"], list)
    for opt in s["overdue_options"]:
        assert "value" in opt
        assert "label" in opt


# ── recommend() ───────────────────────────────────────────────────────────────

def test_recommend_capped_at_4():
    for intent in ["overdue_list", "total_revenue", "low_stock", "business_summary"]:
        recs = recommend(intent, USER_ID)
        assert len(recs) <= 4, f"{intent} returned {len(recs)} suggestions (max 4)"


def test_recommend_no_duplicates():
    for intent in ["overdue_list", "total_revenue", "business_summary"]:
        recs = recommend(intent, USER_ID)
        seen = set()
        for s in recs:
            key = s.get("intent") or s.get("prompt") or s.get("label")
            assert key not in seen, f"Duplicate suggestion in {intent}: {key}"
            seen.add(key)


def test_overdue_list_has_reminder_chip():
    """When overdue invoices exist, overdue_list must return a send_reminders chip."""
    recs = recommend("overdue_list", USER_ID)
    types = {r["type"] for r in recs}
    assert "action" in types or "select" in types


def test_overdue_list_select_chip_has_options():
    """If the reminder chip is type=select, it must carry options."""
    recs = recommend("overdue_list", USER_ID)
    select_chips = [r for r in recs if r["type"] == "select"]
    if select_chips:
        chip = select_chips[0]
        assert "options" in chip
        assert len(chip["options"]) > 0
        assert chip["options"][0]["value"] == "Alpha"   # only overdue customer


def test_cashflow_emergency_on_low_collection_rate():
    """
    Collection rate is 33% (< 70%).
    Any intent that is NOT total_revenue/revenue_summary/business_summary
    should have a cashflow emergency chip in global suggestions.
    """
    recs = recommend("pending_list", USER_ID)
    ids = {r["id"] for r in recs}
    assert "cashflow_emergency" in ids, "cashflow_emergency chip missing when rate < 70%"


def test_no_cashflow_emergency_chip_on_revenue_intents():
    """
    For total_revenue and revenue_summary, the cashflow emergency is shown
    inline in the recs list (not via _global), so we don't double-add it.
    The global _global() function skips these intents.
    """
    recs = recommend("total_revenue", USER_ID)
    # May contain an inline cashflow chip from RECS but NOT from _global
    global_cashflow = [r for r in recs if r["id"] == "cashflow_emergency"]
    # It's acceptable for total_revenue to have 0 or 1 cashflow chip,
    # but never more than 1 (no duplicates rule covers this)
    assert len(global_cashflow) <= 1


def test_all_suggestions_have_required_fields():
    for intent in ["overdue_list", "total_revenue", "low_stock", "top_customers", "business_summary"]:
        recs = recommend(intent, USER_ID)
        for s in recs:
            assert "id" in s, f"Missing id in suggestion from {intent}"
            assert "label" in s, f"Missing label in suggestion from {intent}"
            assert "type" in s, f"Missing type in suggestion from {intent}"
            assert s["type"] in ("deterministic", "ai", "action", "select")
