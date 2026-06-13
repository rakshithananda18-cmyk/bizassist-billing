"""
tests/test_charts.py
====================
Unit tests for build_chart_data service.
"""

import os
import sys

os.environ["DATABASE_URL"] = "sqlite:///./test_bizassist.db"
os.environ["GROQ_API_KEY"] = "mock_groq_api_key"

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, backend_path)

import pytest
from database.db import SessionLocal
from database.models import Base, Invoice
from services.charts import build_chart_data

BID = 883344


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
        db.commit()
    finally:
        db.close()


def _seed():
    db = SessionLocal()
    try:
        db.add_all([
            Invoice(business_id=BID, invoice_id="C-1", customer="Annapurna", product="Rice", amount=1500, status="Paid",    invoice_date="2026-01-15", due_date="2026-01-30"),
            Invoice(business_id=BID, invoice_id="C-2", customer="Annapurna", product="Rice", amount=2500, status="Overdue", invoice_date="2026-01-20", due_date="2026-02-04"),
            Invoice(business_id=BID, invoice_id="C-3", customer="Star Bazaar", product="Oil",  amount=800,  status="Pending", invoice_date="2026-02-10", due_date="2026-02-25"),
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


def test_build_chart_data_returns_none_if_no_chart_intent():
    assert build_chart_data("show my overdue list", BID) is None


def test_build_chart_data_line_chart_monthly_trend():
    chart = build_chart_data("plot monthly trend graph", BID)
    assert chart is not None
    assert chart["type"] == "line"
    assert chart["title"] == "Monthly Revenue Trend"
    # Annapurna (1500 + 2500 = 4000) for Jan, Star Bazaar (800) for Feb
    assert "Jan 2026" in chart["labels"]
    assert "Feb 2026" in chart["labels"]
    assert chart["datasets"][0]["data"] == [4000.0, 800.0]


def test_build_chart_data_doughnut_chart_by_status():
    chart = build_chart_data("show chart of revenue status", BID)
    assert chart is not None
    assert chart["type"] == "doughnut"
    assert chart["title"] == "Revenue by Status"
    assert "Paid" in chart["labels"]
    assert "Overdue" in chart["labels"]
    assert "Pending" in chart["labels"]


def test_build_chart_data_bar_chart_top_customers():
    chart = build_chart_data("visualize top customers chart", BID)
    assert chart is not None
    assert chart["type"] == "bar"
    assert chart["title"] == "Top Customers by Revenue"
    assert "Annapurna" in chart["labels"]
    assert "Star Bazaar" in chart["labels"]
    # Annapurna: 4000, Star Bazaar: 800
    assert chart["datasets"][0]["data"] == [4000.0, 800.0]


def test_build_chart_data_default_bar_chart():
    # Matches chart keyword, but not specific subcategories -> default status breakdown bar chart
    chart = build_chart_data("show me a graph", BID)
    assert chart is not None
    assert chart["type"] == "bar"
    assert chart["title"] == "Invoice Status Breakdown"
