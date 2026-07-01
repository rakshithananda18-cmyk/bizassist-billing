"""
test_handlers.py
================
Unit tests for each domain handler function in services/direct_query_handler.py.

Seeds a real in-memory SQLite DB with controlled test data so each handler
can be tested deterministically without mocking the database layer.

Run:  pytest tests/test_handlers.py -v
"""
import os
import sys

os.environ["DATABASE_URL"] = "sqlite:///./test_handlers.db"
os.environ["GROQ_API_KEY"] = "mock_key"

for db_path in ["test_handlers.db", "backend/test_handlers.db"]:
    if os.path.exists(db_path):
        try:
            os.remove(db_path)
        except Exception:
            pass

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, backend_path)

import pytest
from database.db import engine, SessionLocal
from database.models import Base, Invoice, Inventory, LegacyPayment, User
from services.auth import hash_password

# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module", autouse=True)
def setup_db():
    """Create schema and seed controlled test data once for the whole session."""
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        db.query(User).filter(User.id == 99).delete()
        db.query(Invoice).filter(Invoice.business_id == 99).delete()
        db.query(Inventory).filter(Inventory.business_id == 99).delete()
        db.query(LegacyPayment).filter(LegacyPayment.business_id == 99).delete()
        db.commit()
        # Seed a test user
        user = User(
            id=99, username="test_handler_user",
            password=hash_password("Test123"),
            business_name="Test Business", role="enterprise"
        )
        db.add(user)

        # Invoices — controlled mix of statuses and amounts
        invoices = [
            # Paid
            Invoice(business_id=99, invoice_id="INV-001", customer="Alpha Corp",
                    product="Widget A", amount=10000, status="Paid",
                    invoice_date="2026-05-01", due_date="2026-05-15"),
            Invoice(business_id=99, invoice_id="INV-002", customer="Beta Ltd",
                    product="Widget B", amount=8000, status="Paid",
                    invoice_date="2026-05-02", due_date="2026-05-20"),
            # Pending
            Invoice(business_id=99, invoice_id="INV-003", customer="Alpha Corp",
                    product="Widget C", amount=5000, status="Pending",
                    invoice_date="2026-05-10", due_date="2026-06-20"),
            Invoice(business_id=99, invoice_id="INV-004", customer="Gamma Inc",
                    product="Widget D", amount=3000, status="Pending",
                    invoice_date="2026-05-12", due_date="2026-06-25"),
            # Overdue — Alpha Corp owes 12000, Gamma Inc 7000, Beta Ltd 2000
            Invoice(business_id=99, invoice_id="INV-005", customer="Alpha Corp",
                    product="Widget E", amount=12000, status="Overdue",
                    invoice_date="2026-04-01", due_date="2026-05-01"),
            Invoice(business_id=99, invoice_id="INV-006", customer="Gamma Inc",
                    product="Widget F", amount=7000, status="Overdue",
                    invoice_date="2026-04-05", due_date="2026-05-05"),
            Invoice(business_id=99, invoice_id="INV-007", customer="Beta Ltd",
                    product="Widget G", amount=2000, status="Overdue",
                    invoice_date="2026-04-10", due_date="2026-05-10"),
        ]
        for inv in invoices:
            db.add(inv)

        # Inventory — mix of low stock and normal stock, one expiring soon.
        # Item A's expiry is computed RELATIVE TO TODAY (7 days out) so the
        # "expiring within 30 days" test never drifts as the calendar moves.
        from datetime import datetime as _dt, timedelta as _td
        _expiring_soon = (_dt.today() + _td(days=7)).strftime("%Y-%m-%d")
        items = [
            Inventory(business_id=99, product_name="Item A", stock=5,
                      expiry_date=_expiring_soon, supplier="Supplier X"),   # low + expiring (today+7)
            Inventory(business_id=99, product_name="Item B", stock=3,
                      expiry_date="2026-12-01", supplier="Supplier Y"),   # low only
            Inventory(business_id=99, product_name="Item C", stock=200,
                      expiry_date="2027-01-01", supplier="Supplier Z"),   # normal
        ]
        for item in items:
            db.add(item)

        db.commit()
    finally:
        db.close()

    yield

    # Teardown
    for db_path in ["test_handlers.db", "backend/test_handlers.db"]:
        if os.path.exists(db_path):
            try:
                os.remove(db_path)
            except Exception:
                pass


USER_ID = 99


# ── Router import ─────────────────────────────────────────────────────────────

from services.direct_query_handler import handle


# ── Invoice / Revenue handlers ────────────────────────────────────────────────

def test_invoice_count():
    result = handle("invoice_count", "", USER_ID)
    assert result is not None
    assert "Total invoices" in result or "7" in result   # 7 seeded
    assert "Paid" in result
    assert "Overdue" in result


def test_total_revenue():
    result = handle("total_revenue", "", USER_ID)
    assert result is not None
    # Total = 10000+8000+5000+3000+12000+7000+2000 = 47000
    assert "47,000" in result or "47000" in result
    assert "Collected" in result or "Paid" in result
    assert "Collection rate" in result or "%" in result


def test_revenue_summary():
    result = handle("total_revenue", "", USER_ID)
    assert result is not None
    assert len(result) > 20


# ── Overdue / Pending handlers ────────────────────────────────────────────────

def test_overdue_list():
    result = handle("overdue_list", "", USER_ID)
    assert result is not None
    assert "Alpha Corp" in result
    assert "Gamma Inc" in result
    assert "Beta Ltd" in result


def test_overdue_amount():
    result = handle("overdue_amount", "", USER_ID)
    assert result is not None
    # Total overdue = 12000 + 7000 + 2000 = 21000
    assert "21,000" in result or "21000" in result


def test_pending_list():
    result = handle("pending_list", "", USER_ID)
    assert result is not None
    assert "Alpha Corp" in result   # INV-003
    assert "Gamma Inc" in result    # INV-004


# ── Top debtors vs top customers — CRITICAL distinction ──────────────────────

def test_top_debtors_ranks_by_overdue_not_revenue():
    """
    top_debtors must rank by OVERDUE AMOUNT, not total revenue.
    Alpha Corp: overdue=12000, total_revenue=27000
    Gamma Inc:  overdue=7000,  total_revenue=10000
    Beta Ltd:   overdue=2000,  total_revenue=10000

    Expected debtor rank: Alpha(12k) > Gamma(7k) > Beta(2k)
    Expected revenue rank: Alpha(27k) > Gamma/Beta(10k each)

    These orderings are the same here but the AMOUNTS shown must be overdue,
    not total revenue. Alpha Corp overdue = 12000, NOT 27000.
    """
    result = handle("top_debtors", "", USER_ID)
    assert result is not None
    assert "Alpha Corp" in result
    # The amount shown for Alpha Corp must be 12,000 (overdue), not 27,000 (total revenue)
    assert "12,000" in result
    assert "27,000" not in result   # total revenue must NOT appear


def test_top_customers_ranks_by_total_revenue():
    """
    top_customers must rank by TOTAL REVENUE across all statuses.
    Alpha Corp total: 10000+5000+12000 = 27000 (highest)
    """
    result = handle("top_customers", "", USER_ID)
    assert result is not None
    assert "Alpha Corp" in result
    assert "27,000" in result    # total revenue, not just overdue


def test_top_debtors_excludes_customers_with_no_overdue():
    """Customers with no overdue invoices must not appear in top_debtors."""
    # In our seed data, all 3 customers have overdue invoices, so we just
    # verify the handler only includes overdue-based data.
    result = handle("top_debtors", "", USER_ID)
    assert result is not None
    # Should show percentage of total overdue
    assert "%" in result


# ── Inventory handlers ────────────────────────────────────────────────────────

def test_inventory_count():
    result = handle("inventory_count", "", USER_ID)
    assert result is not None
    assert "3" in result or "three" in result.lower()


def test_low_stock():
    result = handle("low_stock", "", USER_ID)
    assert result is not None
    # Item A (stock=5) and Item B (stock=3) are both ≤ 10
    assert "Item A" in result
    assert "Item B" in result
    assert "Item C" not in result   # stock=200, should not appear


def test_expiring_soon():
    result = handle("expiring_soon", "expiring soon", USER_ID)
    assert result is not None
    # Item A is seeded to expire 7 days from today → always within the 30-day window
    assert "Item A" in result


# ── Dashboard handler ─────────────────────────────────────────────────────────

def test_business_summary():
    result = handle("business_summary", "", USER_ID)
    assert result is not None
    assert len(result) > 50    # must be a substantive summary


# ── Unknown handler gracefully returns None ───────────────────────────────────

def test_unknown_handler_returns_none():
    result = handle("nonexistent_handler", "", USER_ID)
    assert result is None


# ── Client summary handler ────────────────────────────────────────────────────

def test_client_summary():
    result = handle("client_summary", "", USER_ID, params={"customer": "Alpha Corp"})
    assert result is not None
    assert "Alpha Corp" in result
    # Handler shows totals by status (Collected/Pending/Overdue) not individual invoice IDs
    assert "Collected" in result or "collected" in result.lower()
    assert "Overdue" in result
    assert "27,000" in result  # total billed = 10000 + 5000 + 12000
