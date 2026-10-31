"""
Regression test suite for Work Package 1: Canonical Financial/Stock Contracts.
Guarantees verified for BD-02, BD-03, BD-04, BD-06, BD-10, BD-12, BD-13.
"""
import json
import pytest
from unittest.mock import patch
from sqlalchemy import create_engine, func
from sqlalchemy.orm import sessionmaker

from database.models import Base, User, Product, Inventory, Invoice, PurchaseInvoice
from core.models import B2BConnection
from core.stock import ledger
from core.billing import commands as billing
from core.purchase import commands as purchase
from core.order import service as orders
from core.api import reports
from services.tools import business as business_tools


@pytest.fixture
def wp1_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as db:
        owner = User(id=920001, username="wp1_owner", public_id="BA-WP1-OWNER",
                     password="unusable", state_code="29", business_name="WP1 fixture",
                     settings=json.dumps({"transactions": {"round_off_enabled": False}}))
        buyer = User(id=920002, username="wp1_buyer", public_id="BA-WP1-BUYER",
                     password="unusable", state_code="29", business_name="WP1 buyer")
        db.add_all([owner, buyer])
        db.commit()
        yield db, owner, buyer


def test_bd02_stock_ledger_exact_bucket_no_duplication(wp1_db):
    """BD-02: default warehouse/unbatched movements must not duplicate stock in cache."""
    db, owner, _ = wp1_db
    p = Product(business_id=owner.id, name="Batched product", unit="Nos",
                selling_price=100, cost_price=60, track_inventory=True,
                is_active=True, cgst_rate=0, sgst_rate=0, igst_rate=0)
    db.add(p)
    db.flush()
    for batch, qty in [("B1", 5), ("B2", 7)]:
        ledger.record_movement(db, business_id=owner.id, movement_type=ledger.OPENING,
                               qty_delta=qty, product_id=p.id,
                               product_name=p.name, batch_no=batch)
    db.commit()
    ledger.record_movement(db, business_id=owner.id, movement_type=ledger.SALE,
                           qty_delta=-1, product_id=p.id, product_name=p.name)
    db.commit()

    ledger_total = ledger.current_stock(db, owner.id, product_id=p.id)
    inv_sum = db.query(func.sum(Inventory.stock)).filter(
        Inventory.business_id == owner.id, Inventory.product_id == p.id).scalar()
    assert ledger_total == 11.0
    assert inv_sum == 11.0


def test_bd03_purchase_pack_price_stored_as_base_unit_cost(wp1_db):
    """BD-03: carton price normalized to base-unit cost."""
    db, owner, _ = wp1_db
    pur = purchase.accept_supplier_invoice(db, owner.id, {
        "supplier_name": "Carton supplier", "invoice_number": "CARTON-WP1",
        "invoice_date": "2026-10-30", "items": [{
            "product_name": "Carton item WP1",
            "quantity": 1, "conversion_factor": 12, "purchase_unit": "Carton", "unit": "Nos",
            "unit_price": 120
        }],
    })
    carton_prod = db.query(Product).filter(Product.name == "Carton item WP1").one()
    carton_inv = db.query(Inventory).filter(Inventory.product_id == carton_prod.id).one()
    assert pur.total_amount == 120.0
    assert carton_inv.stock == 12.0
    assert carton_inv.cost_price == 10.0
    assert carton_inv.stock * carton_inv.cost_price == 120.0


def test_bd12_supplier_catalogue_multi_bucket_sum(wp1_db):
    """BD-12: catalogue aggregates across all warehouse/batch buckets."""
    db, owner, buyer = wp1_db
    conn = B2BConnection(seller_business_id=owner.id, buyer_business_id=buyer.id,
                         status="accepted", price_tier="standard", discount_pct=0,
                         stock_visibility="exact")
    db.add(conn)
    db.commit()

    cat_prod = Product(business_id=owner.id, name="Multi-bucket product", unit="Nos",
                       selling_price=50, track_inventory=True, is_active=True,
                       cgst_rate=0, sgst_rate=0, igst_rate=0)
    db.add(cat_prod)
    db.flush()
    for batch, qty in [("MB1", 5), ("MB2", 7)]:
        ledger.record_movement(db, business_id=owner.id, movement_type=ledger.OPENING,
                               qty_delta=qty, product_id=cat_prod.id,
                               product_name=cat_prod.name, batch_no=batch)
    db.commit()
    catalog = orders.get_supplier_catalog(db, buyer.id, owner.id)
    cat_stock = next(row["stock"] for row in catalog if row["product_id"] == cat_prod.id)
    assert cat_stock == 12.0


def test_bd06_b2b_order_quote_and_invoice_gst_match(wp1_db):
    """BD-06: B2B order and final invoice deterministic intra/inter GST alignment."""
    db, owner, buyer = wp1_db
    conn = B2BConnection(seller_business_id=owner.id, buyer_business_id=buyer.id,
                         status="accepted", price_tier="standard", discount_pct=0,
                         stock_visibility="exact")
    db.add(conn)
    db.commit()

    taxable_prod = Product(business_id=owner.id, name="GST 18 item", unit="Nos",
                           selling_price=100, track_inventory=False, is_active=True,
                           cgst_rate=9, sgst_rate=9, igst_rate=18)
    db.add(taxable_prod)
    db.commit()
    order = orders.create_order(db, buyer.id, owner.id, [{"product_id": taxable_prod.id, "quantity": 1}])
    orders.transition_order_status(db, owner.id, order.id, "accepted")
    orders.transition_order_status(db, owner.id, order.id, "packed")
    orders.transition_order_status(db, owner.id, order.id, "dispatched")
    orders.transition_order_status(db, owner.id, order.id, "completed")
    final_sale = db.query(Invoice).filter(Invoice.id == order.seller_invoice_id).one()
    assert order.total_amount == 118.0
    assert final_sale.total_amount == 118.0


def test_bd04_ai_overview_net_revenue_and_receipts(wp1_db):
    """BD-04: AI metrics treat returns as deduction, not new revenue or cash."""
    db, owner, _ = wp1_db
    with patch.object(business_tools, "SessionLocal", lambda: db):
        before_ai = json.loads(business_tools.get_business_overview(owner.id))

    ai_prod = Product(business_id=owner.id, name="AI Return Prod", unit="Nos",
                      selling_price=100, track_inventory=False, is_active=True,
                      cgst_rate=0, sgst_rate=0, igst_rate=0)
    db.add(ai_prod)
    db.commit()
    sale_inv = billing.create_sale_invoice(db, business_id=owner.id, invoice_no="AI-RET-1",
                                           lines=[{"product_id": ai_prod.id, "quantity": 1, "unit_price": 100}])
    billing.create_credit_note(db, business_id=owner.id, original_invoice_id=sale_inv.id,
                               lines=[{"product_id": ai_prod.id, "quantity": 1}])

    with patch.object(business_tools, "SessionLocal", lambda: db):
        after_ai = json.loads(business_tools.get_business_overview(owner.id))

    delta_rev = after_ai["total_revenue"] - before_ai["total_revenue"]
    delta_collected = after_ai["collected_revenue"] - before_ai["collected_revenue"]
    assert delta_rev == 0.0
    assert delta_collected == 0.0


def test_bd10_immutable_cost_snapshot_for_historical_cogs(wp1_db):
    """BD-10: changing today's product cost price does not change prior period COGS."""
    db, owner, _ = wp1_db
    profit_prod = Product(business_id=owner.id, name="Profit Prod", unit="Nos",
                          selling_price=150, cost_price=80, track_inventory=False, is_active=True,
                          cgst_rate=0, sgst_rate=0, igst_rate=0)
    db.add(profit_prod)
    db.commit()
    billing.create_sale_invoice(db, business_id=owner.id, invoice_no="PROFIT-1",
                                invoice_date="2026-01-01",
                                lines=[{"product_id": profit_prod.id, "quantity": 1, "unit_price": 150}])
    pl_before = reports.report_pnl(from_date="2026-01-01", to_date="2026-01-02", current_user={"id": owner.id}, db=db)
    cogs_before = next(item["amount"] for item in pl_before if item["metric"] == "Cost of Goods Sold (COGS)")
    assert cogs_before == 80.0

    profit_prod.cost_price = 140.0
    db.commit()

    pl_after = reports.report_pnl(from_date="2026-01-01", to_date="2026-01-02", current_user={"id": owner.id}, db=db)
    cogs_after = next(item["amount"] for item in pl_after if item["metric"] == "Cost of Goods Sold (COGS)")
    assert cogs_after == 80.0


def test_bd13_debit_note_monotonic_numbering(wp1_db):
    """BD-13: debit note numbering allocates monotonic series DN-0001, DN-0002."""
    db, owner, _ = wp1_db
    pur1 = purchase.accept_supplier_invoice(db, owner.id, {
        "supplier_name": "Supplier 1", "invoice_number": "PUR-1",
        "invoice_date": "2026-10-30", "items": [{"product_name": "Item 1", "quantity": 1, "unit_price": 50}],
    })
    pur2 = purchase.accept_supplier_invoice(db, owner.id, {
        "supplier_name": "Supplier 2", "invoice_number": "PUR-2",
        "invoice_date": "2026-10-30", "items": [{"product_name": "Item 2", "quantity": 1, "unit_price": 75}],
    })
    p1 = db.query(Product).filter(Product.name == "Item 1").one()
    p2 = db.query(Product).filter(Product.name == "Item 2").one()

    dn1 = purchase.create_debit_note(db, business_id=owner.id, original_purchase_id=pur1.id,
                                     lines=[{"product_id": p1.id, "quantity": 1}])
    dn2 = purchase.create_debit_note(db, business_id=owner.id, original_purchase_id=pur2.id,
                                     lines=[{"product_id": p2.id, "quantity": 1}])
    assert dn1.invoice_number == "DN-0001"
    assert dn2.invoice_number == "DN-0002"
