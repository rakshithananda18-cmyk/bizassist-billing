"""
tests/test_negative_stock_policy.py
===================================
P0 billing pack — the negative-stock policy guard in `create_sale_invoice`.

Locks in:
  • default (toggle off) keeps historical behaviour: oversell permitted,
    ledger goes negative
  • toggle ON (transactions.prevent_negative_stock in the owner's settings blob)
    rejects a sale that would take a tracked product below zero — BEFORE
    anything is written (no invoice, no lines, no stock movement, no journal)
  • quantities aggregate per product across cart lines
  • selling exactly the available quantity is allowed in 'block' mode
  • non-tracked products and custom lines are exempt

Pure DB unit test (SQLite), mirroring tests/test_billing.py conventions.
"""
import os
import sys
import json

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_bizassist.db")
os.environ.setdefault("GROQ_API_KEY", "mock_groq_api_key")

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, backend_path)

import pytest
from database.db import SessionLocal
from database.models import Base, Product, Invoice, InvoiceLineItem, Inventory, User
from core.models import StockLedger, JournalEntry, JournalLine
from core.billing import commands as billing
from core.stock import ledger as SL

BID = 700800


def _ensure_schema():
    db = SessionLocal()
    try:
        Base.metadata.create_all(bind=db.get_bind())
    finally:
        db.close()


def _clear():
    db = SessionLocal()
    try:
        ids = [r.id for r in db.query(Invoice.id).filter(Invoice.business_id == BID).all()]
        if ids:
            db.query(InvoiceLineItem).filter(InvoiceLineItem.invoice_id.in_(ids)).delete(synchronize_session=False)
        db.query(Invoice).filter(Invoice.business_id == BID).delete()
        entry_ids = [r.id for r in db.query(JournalEntry.id).filter(JournalEntry.business_id == BID).all()]
        if entry_ids:
            db.query(JournalLine).filter(JournalLine.entry_id.in_(entry_ids)).delete(synchronize_session=False)
        db.query(JournalEntry).filter(JournalEntry.business_id == BID).delete()
        db.query(StockLedger).filter(StockLedger.business_id == BID).delete()
        db.query(Inventory).filter(Inventory.business_id == BID).delete()
        db.query(Product).filter(Product.business_id == BID).delete()
        db.query(User).filter(User.id == BID).delete()
        db.commit()
    finally:
        db.close()


def _block_negative(db, on=True):
    """Flip the owner's transactions.prevent_negative_stock toggle (the real
    Settings switch) via the User.settings JSON blob."""
    owner = db.query(User).filter(User.id == BID).first()
    blob = json.loads(owner.settings) if owner.settings else {}
    blob.setdefault("transactions", {})["prevent_negative_stock"] = on
    owner.settings = json.dumps(blob)
    db.commit()


@pytest.fixture()
def db():
    _ensure_schema()
    _clear()
    session = SessionLocal()
    # business user (state 29 → intra-state) + one tracked and one non-tracked product
    session.add(User(id=BID, username=f"negstock_biz_{BID}", password="x", state_code="29"))
    session.add(Product(business_id=BID, name="Tracked Widget", selling_price=100.0,
                        cgst_rate=0, sgst_rate=0, igst_rate=0, track_inventory=True))
    session.add(Product(business_id=BID, name="Service Fee", selling_price=50.0,
                        cgst_rate=0, sgst_rate=0, igst_rate=0, track_inventory=False))
    session.commit()
    yield session
    session.close()


def _pid(db, name):
    return db.query(Product).filter(Product.business_id == BID, Product.name == name).first().id


def _stock_in(db, pid, qty):
    SL.record_movement(db, business_id=BID, movement_type=SL.PURCHASE, qty_delta=qty,
                       product_id=pid, product_name="Tracked Widget",
                       reference_type="test", reference_id=0)
    db.commit()


def _sale(db, lines, **kw):
    return billing.create_sale_invoice(db, business_id=BID, lines=lines, **kw)


def test_default_policy_allows_oversell(db):
    pid = _pid(db, "Tracked Widget")
    _stock_in(db, pid, 2)
    inv = _sale(db, [{"product_id": pid, "quantity": 10, "unit_price": 100}])
    assert inv.id is not None
    assert SL.current_stock(db, BID, product_id=pid) == -8.0


def test_block_policy_rejects_oversell_and_writes_nothing(db):
    _block_negative(db)
    pid = _pid(db, "Tracked Widget")
    _stock_in(db, pid, 5)
    before_invoices = db.query(Invoice).filter(Invoice.business_id == BID).count()
    before_moves = db.query(StockLedger).filter(StockLedger.business_id == BID).count()

    with pytest.raises(ValueError, match="Insufficient stock"):
        _sale(db, [{"product_id": pid, "quantity": 6, "unit_price": 100}])
    db.rollback()

    assert db.query(Invoice).filter(Invoice.business_id == BID).count() == before_invoices
    assert db.query(StockLedger).filter(StockLedger.business_id == BID).count() == before_moves
    assert db.query(JournalEntry).filter(JournalEntry.business_id == BID).count() == 0
    assert SL.current_stock(db, BID, product_id=pid) == 5.0


def test_block_policy_aggregates_lines_per_product(db):
    _block_negative(db)
    pid = _pid(db, "Tracked Widget")
    _stock_in(db, pid, 5)
    # 3 + 3 across two lines = 6 > 5 available → blocked even though each line fits
    with pytest.raises(ValueError, match="Insufficient stock"):
        _sale(db, [
            {"product_id": pid, "quantity": 3, "unit_price": 100},
            {"product_id": pid, "quantity": 3, "unit_price": 100},
        ])
    db.rollback()


def test_block_policy_allows_exact_available_quantity(db):
    _block_negative(db)
    pid = _pid(db, "Tracked Widget")
    _stock_in(db, pid, 5)
    inv = _sale(db, [{"product_id": pid, "quantity": 5, "unit_price": 100}])
    assert inv.id is not None
    assert SL.current_stock(db, BID, product_id=pid) == 0.0


def test_block_policy_exempts_non_tracked_and_custom_lines(db):
    _block_negative(db)
    svc = _pid(db, "Service Fee")
    # non-tracked product + a custom named line: both fine with zero stock
    inv = _sale(db, [
        {"product_id": svc, "quantity": 3, "unit_price": 50},
        {"product_name": "Hand-typed item", "quantity": 2, "unit_price": 10},
    ])
    assert inv.id is not None
