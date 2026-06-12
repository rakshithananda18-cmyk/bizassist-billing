"""
tests/test_smart_insights.py
============================
The advisor's foundation is a DETERMINISTIC snapshot — pure SQL, no model. These
pin its correctness (the grounding the LLM reasoning depends on) and the
model-free fallback so the feature never shows nothing.
"""
import os
import sys

os.environ["DATABASE_URL"] = "sqlite:///./test_bizassist.db"
os.environ["GROQ_API_KEY"] = "mock_groq_api_key"

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, backend_path)

import pytest
from database.db import SessionLocal
from database.models import Base, Invoice, Inventory
from services.smart_insights import (
    build_snapshot, generate_insights, _deterministic_headline, build_panel_insights,
)

BID = 553311


def _ensure_schema():
    db = SessionLocal()
    try:
        Base.metadata.create_all(bind=db.get_bind())
    finally:
        db.close()


def _clear():
    db = SessionLocal()
    try:
        db.query(Invoice).filter(Invoice.business_id == BID).delete()
        db.query(Inventory).filter(Inventory.business_id == BID).delete()
        db.commit()
    finally:
        db.close()


def _seed():
    db = SessionLocal()
    try:
        db.add_all([
            Invoice(business_id=BID, invoice_id="A-INV-1", customer="Acme",   product="Rice",   amount=1000, status="Paid",    due_date="2025-01-10"),
            Invoice(business_id=BID, invoice_id="A-INV-2", customer="Acme",   product="Rice",   amount=4000, status="Overdue", due_date="2024-01-10"),
            Invoice(business_id=BID, invoice_id="B-INV-1", customer="Bharat", product="Wheat",  amount=2000, status="Overdue", due_date="2025-06-01"),
            Invoice(business_id=BID, invoice_id="B-INV-2", customer="Bharat", product="Wheat",  amount=500,  status="Pending", due_date="2026-09-01"),
        ])
        db.add_all([
            Inventory(business_id=BID, product_name="Rice",  stock="50", expiry_date="2030-01-01"),
            Inventory(business_id=BID, product_name="Sugar", stock="5",  expiry_date="2030-01-01"),  # low stock, never invoiced → dead
        ])
        db.commit()
    finally:
        db.close()


@pytest.fixture(autouse=True)
def _setup():
    _ensure_schema()
    _clear()
    _seed()
    yield
    _clear()


def test_snapshot_collections_are_exact():
    snap = build_snapshot(BID)
    assert snap["has_data"] is True
    c = snap["collections"]
    assert c["total_revenue"] == 7500
    assert c["collected"] == 1000
    assert c["overdue_amount"] == 6000
    assert c["overdue_count"] == 2
    assert c["pending_count"] == 1
    assert c["collection_rate"] == round(1000 / 7500 * 100)


def test_snapshot_top_debtors_and_concentration():
    snap = build_snapshot(BID)
    debtors = {d["customer"]: d["overdue"] for d in snap["top_debtors"]}
    assert debtors["Acme"] == 4000 and debtors["Bharat"] == 2000
    # Acme billed 5000 of 7500 total → 67% concentration
    assert snap["customers"]["top_concentration_pct"] == round(5000 / 7500 * 100)
    assert snap["customers"]["count"] == 2


def test_snapshot_products_fast_and_dead():
    snap = build_snapshot(BID)
    fast = [p["product"] for p in snap["products"]["fast_movers"]]
    assert "Rice" in fast and "Wheat" in fast
    dead = [d["product"] for d in snap["products"]["dead_stock"]]
    assert "Sugar" in dead   # in stock, never invoiced


def test_empty_business_has_no_data():
    _clear()
    snap = build_snapshot(BID)
    assert snap["has_data"] is False


def test_deterministic_headline_cites_real_overdue():
    snap = build_snapshot(BID)
    head = _deterministic_headline(snap)
    overdue = [h for h in head if h["dimension"] == "collections" and h.get("polarity") == "improve"]
    assert overdue, "overdue headline missing"
    assert "6,000" in overdue[0]["insight"]


def test_panel_split_positives_and_improvements():
    panel = build_panel_insights(BID)
    assert panel["has_data"] is True
    pos = [p["title"] for p in panel["positives"]]
    imp = [p["title"] for p in panel["improvements"]]
    assert "Top-selling product" in pos
    assert "Overdue cash to collect" in imp
    assert "Customer concentration risk" in imp   # Acme is 67% of revenue
    for it in panel["positives"] + panel["improvements"]:
        assert it["title"] and it["detail"]   # grounded, structured


def test_panel_empty_business():
    _clear()
    panel = build_panel_insights(BID)
    assert panel["has_data"] is False
    assert panel["positives"] == [] and panel["improvements"] == []


def test_generate_insights_falls_back_without_model(monkeypatch):
    # Force the Groq call to fail → deterministic fallback, never an exception.
    import services.smart_insights as si

    class _BoomClient:
        class chat:
            class completions:
                @staticmethod
                def create(*a, **k):
                    raise RuntimeError("no model")

    out = generate_insights(BID, client=_BoomClient())
    assert out["source"] == "deterministic"
    assert out["insights"]   # the headline is present
