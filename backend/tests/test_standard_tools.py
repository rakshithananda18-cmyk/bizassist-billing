"""
tests/test_standard_tools.py
============================
The standard tools that move the agent beyond overdue-only: revenue trend over
time and product performance (incl. dead stock). Pure DB queries — no model.
"""
import os
import sys
import json

os.environ["DATABASE_URL"] = "sqlite:///./test_bizassist.db"
os.environ["GROQ_API_KEY"] = "mock_groq_api_key"

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, backend_path)

import pytest
from database.db import SessionLocal
from database.models import Base, Invoice, Inventory
from services.tools import execute_tool

BID = 771122


def _ensure_schema():
    db = SessionLocal()
    try:
        Base.metadata.create_all(bind=db.get_bind())
    finally:
        db.close()


def _clear():
    db = SessionLocal()
    try:
        for M in (Invoice, Inventory):
            db.query(M).filter(M.business_id == BID).delete()
        db.commit()
    finally:
        db.close()


def _seed():
    db = SessionLocal()
    try:
        db.add_all([
            Invoice(business_id=BID, invoice_id="S-1", customer="A", product="Rice", amount=1000, status="Paid",    invoice_date="2026-01-15", due_date="2026-01-30"),
            Invoice(business_id=BID, invoice_id="S-2", customer="A", product="Rice", amount=2000, status="Overdue", invoice_date="2026-01-20", due_date="2026-02-04"),
            Invoice(business_id=BID, invoice_id="S-3", customer="B", product="Oil",  amount=500,  status="Paid",    invoice_date="2026-02-10", due_date="2026-02-25"),
        ])
        db.add_all([
            Inventory(business_id=BID, product_name="Rice",        stock=50,  supplier="X", cost_price=100, selling_price=150),
            Inventory(business_id=BID, product_name="DeadProduct", stock=100, supplier="X", cost_price=50,  selling_price=60),   # never sold
            Inventory(business_id=BID, product_name="LossLeader",  stock=20,  supplier="X", cost_price=100, selling_price=90),   # below cost
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


def test_revenue_trend_groups_by_month():
    trend = json.loads(execute_tool("revenue_trend", {}, BID))
    by_month = {t["month"]: t for t in trend}
    assert by_month["2026-01"]["billed"] == 3000      # 1000 + 2000
    assert by_month["2026-01"]["collected"] == 1000   # only the Paid one
    assert by_month["2026-01"]["invoices"] == 2
    assert by_month["2026-02"]["billed"] == 500
    assert by_month["2026-02"]["collected"] == 500


def test_product_performance_ranks_and_flags_dead_stock():
    out = json.loads(execute_tool("product_performance", {}, BID))
    top = out["top_products"]
    assert top[0]["product"] == "Rice"          # 3000 billed
    assert top[0]["billed"] == 3000
    assert top[0]["overdue"] == 2000
    assert top[0]["stock"] == 50
    dead = [d["product"] for d in out["dead_stock"]]
    assert "DeadProduct" in dead                # in stock, never invoiced
    assert "Rice" not in dead


def test_top_debtors_unaffected_regression():
    # sanity: the per-customer overdue tool still works alongside the new ones
    out = json.loads(execute_tool("rank_top_debtors", {}, BID))
    assert out[0]["customer"] == "A" and out[0]["overdue_total"] == 2000


@pytest.mark.parametrize("q", [
    "what are my best and worst selling products",
    "show me my top selling products",
    "product performance",
    "which products are slow moving",
])
def test_product_performance_queries_route_direct(q):
    # the misroute bug: these went to inventory_count ('25 products tracked').
    from services.query_router import classify
    assert classify(q) == ("DIRECT", "product_performance")


def test_product_performance_handler_renders_markdown():
    from services.handlers.invoices import _product_performance
    md = _product_performance(BID)
    assert "Product Performance" in md
    assert "Rice" in md
    assert "Dead stock" in md and "DeadProduct" in md


# ── inventory pricing now flows through the uploader (margins unlock) ──────

def test_pricing_columns_map():
    from services.column_mapper import ColumnMapper
    r = ColumnMapper().map_columns(
        ["Product Name", "Qty", "Cost Price", "Selling Price", "Reorder Level", "Supplier"])
    assert set(r.mapping.values()) >= {
        "product_name", "stock", "cost_price", "selling_price", "reorder_point", "supplier"}
    assert r.detected_type == "inventory"


def test_pricing_columns_map_uniqueness():
    from services.column_mapper import ColumnMapper
    # Multiple raw columns (name, sku, description) would all map to 'product_name' if we didn't enforce uniqueness.
    # Similarly, brand and manufacturer would both map to 'supplier'.
    r = ColumnMapper().map_columns(["name", "sku", "description", "brand", "manufacturer", "stock"])
    
    # Check that each canonical column is mapped at most once
    mapped_canonicals = list(r.mapping.values())
    assert len(mapped_canonicals) == len(set(mapped_canonicals))
    
    # Check that renaming a DataFrame results in unique columns
    import pandas as pd
    df = pd.DataFrame(columns=["name", "sku", "description", "brand", "manufacturer", "stock"])
    r_df = ColumnMapper().map_columns(df.columns.tolist(), df=df)
    assert len(r_df.renamed_df.columns) == len(set(r_df.renamed_df.columns))


def test_unit_column_does_not_hijack_stock():
    """Regression: a unit-of-measure column ('unit' = "Nos") must NOT be mapped to the
    integer `stock` field; the real quantity column ('opening_stock') must win instead.
    Previously 'unit' fuzzy-matched the 'units'/'nos' synonyms and routed "Nos" into
    stock, aborting the whole inventory import with a ValueError. (sample_products_import.csv)"""
    from services.column_mapper import ColumnMapper
    cols = ["name", "sku", "barcode", "unit", "description", "brand", "manufacturer",
            "category", "selling_price", "cost_price", "mrp", "cgst_rate", "sgst_rate",
            "igst_rate", "opening_stock"]
    r = ColumnMapper().map_columns(cols, filename="sample_products_import.csv")
    assert "unit" not in r.mapping                          # UoM column ignored, not stock
    assert r.mapping.get("opening_stock") == "stock"        # real quantity wins the slot
    assert r.mapping.get("name") == "product_name"
    assert r.detected_type == "inventory"



def test_product_margins_compute_and_flag():
    out = json.loads(execute_tool("product_margins", {}, BID))
    by = {p["product"]: p for p in out["top_by_profit"]}
    assert by["Rice"]["margin_pct"] == 33.3            # (150-100)/150
    assert by["Rice"]["est_gross_profit"] == 999        # 3000 billed × 33.3%
    assert "LossLeader" in out["below_cost"]            # sells at 90, costs 100
    assert out["blended_margin_pct"] is not None


@pytest.mark.parametrize("q,expected", [
    ("show my profit margins", "profit_summary"),
    ("how profitable are my products", "profit_summary"),
    ("which products are sold below cost", "profit_summary"),
])
def test_profit_queries_route_direct(q, expected):
    from services.query_router import classify
    assert classify(q) == ("DIRECT", expected)


def test_grow_profit_stays_advisory_not_direct_summary():
    # 'increase my profit' is advisory → must NOT be the factual profit_summary handler
    from services.query_router import classify
    route, handler = classify("plan my business to increase my profit")
    assert handler != "profit_summary"


def test_profit_summary_handler_renders():
    from services.handlers.invoices import _profit_summary
    md = _profit_summary(BID)
    assert "Profitability" in md and "Rice" in md
    assert "below cost" in md.lower()


def test_sales_growth_computes_yoy_and_months():
    out = json.loads(execute_tool("sales_growth", {}, BID))
    assert out["this_year_billed"] == 3500          # all seed invoices are 2026
    assert out["latest_month"] == "2026-02"
    assert any(m["month"] == "2026-01" and m["billed"] == 3000 for m in out["recent_months"])


def test_dso_computes():
    out = json.loads(execute_tool("dso", {}, BID))
    assert out["outstanding"] == 2000               # only the Overdue S-2
    assert out["overdue_invoices"] == 1
    assert out["dso_days"] > 0


def test_dormant_customers_lists_quiet_accounts():
    # seed data is Jan/Feb 2026; "now" is months later → both A and B are dormant
    out = json.loads(execute_tool("dormant_customers", {}, BID))
    names = {c["customer"] for c in out["customers"]}
    assert "A" in names
    assert out["customers"][0]["lifetime_revenue"] >= out["customers"][-1]["lifetime_revenue"]


def test_customer_margins_estimates_profit():
    out = json.loads(execute_tool("customer_margins", {}, BID))
    by = {r["customer"]: r for r in out["top_by_profit"]}
    assert by["A"]["est_gross_profit"] == 999        # 3000 Rice billed × 33.3%
    assert by["A"]["margin_pct"] == 33.3


@pytest.mark.parametrize("q,handler", [
    ("are my sales growing", "sales_growth"),
    ("what is my sales growth rate", "sales_growth"),
    ("how fast am I getting paid", "dso_summary"),
    ("what is my dso", "dso_summary"),
    ("which customers are dormant", "dormant_customers"),
    ("show me lapsed customers", "dormant_customers"),
    ("which customers are most profitable", "customer_margins"),
    ("margin by customer", "customer_margins"),
])
def test_new_standard_queries_route_direct(q, handler):
    # plain phrasings hit the instant DIRECT handler...
    from services.query_router import classify
    assert classify(q) == ("DIRECT", handler)


@pytest.mark.parametrize("q", [
    "what is my year over year growth",        # 'year' is a COMPLEX trigger
    "analyse my customer profitability",        # 'analyse'/'profitability'
])
def test_analytical_phrasings_go_complex(q):
    # ...while analytical phrasings go to AI_COMPLEX, where the loop has the same
    # tools (sales_growth / customer_margins) to answer them.
    from services.query_router import classify
    assert classify(q)[0] == "AI_COMPLEX"
    import pandas as pd
    from services.parser import save_inventory
    from database.models import Inventory
    df = pd.DataFrame([{
        "product_name": "PricedItem", "stock": 30, "expiry_date": "2030-01-01",
        "supplier": "X", "cost_price": 100.0, "selling_price": 130.0, "reorder_point": 15,
    }])
    db = SessionLocal()
    try:
        save_inventory(df, db, BID)
        row = db.query(Inventory).filter(
            Inventory.business_id == BID, Inventory.product_name == "PricedItem").first()
        assert row.cost_price == 100.0
        assert row.selling_price == 130.0
        assert row.reorder_point == 15
    finally:
        db.close()
