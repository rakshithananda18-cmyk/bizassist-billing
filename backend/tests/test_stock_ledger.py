"""
tests/test_stock_ledger.py
==========================
Foundation tests for the append-only stock ledger (D4). These lock in the core
guarantees the whole billing/purchase/order stack will rely on:

  • current_stock = SUM(movements)        (the ledger is the truth)
  • inventory.stock tracks the ledger      (cache stays in step)
  • rebuild_inventory_cache recomputes      (cache is disposable)
  • corrections are NEW rows, never edits   (append-only)
  • unknown movement types are rejected

Pure DB unit tests — no app/router/Groq import needed.
"""
import os
import sys

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_bizassist.db")
os.environ.setdefault("GROQ_API_KEY", "mock_groq_api_key")

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, backend_path)

import pytest
from database.db import SessionLocal
from database.models import Base, Inventory
from core.models import StockLedger
from core.stock import ledger as SL

BID = 770001


def _ensure_schema():
    db = SessionLocal()
    try:
        Base.metadata.create_all(bind=db.get_bind())
    finally:
        db.close()


def _clear():
    db = SessionLocal()
    try:
        db.query(StockLedger).filter(StockLedger.business_id == BID).delete()
        db.query(Inventory).filter(Inventory.business_id == BID).delete()
        db.commit()
    finally:
        db.close()


@pytest.fixture(autouse=True)
def _setup():
    _ensure_schema()
    _clear()
    yield
    _clear()


def _seed_inventory(name="Basmati Rice 25kg", stock=0):
    db = SessionLocal()
    try:
        inv = Inventory(business_id=BID, product_name=name, stock=stock)
        db.add(inv)
        db.commit()
    finally:
        db.close()


# ── current_stock = SUM(movements) ───────────────────────────────────────────

def test_current_stock_is_sum_of_movements():
    name = "Sugar 50kg"
    db = SessionLocal()
    try:
        SL.record_movement(db, business_id=BID, movement_type=SL.OPENING,
                           qty_delta=100, product_name=name, update_cache=False)
        SL.record_movement(db, business_id=BID, movement_type=SL.PURCHASE,
                           qty_delta=50, product_name=name, update_cache=False)
        SL.record_movement(db, business_id=BID, movement_type=SL.SALE,
                           qty_delta=-30, product_name=name, update_cache=False)
        db.commit()
        assert SL.current_stock(db, BID, product_name=name) == 120.0
    finally:
        db.close()


def test_balance_after_is_running_total():
    name = "Toor Dal 5kg"
    db = SessionLocal()
    try:
        r1 = SL.record_movement(db, business_id=BID, movement_type=SL.PURCHASE,
                                qty_delta=40, product_name=name, update_cache=False)
        r2 = SL.record_movement(db, business_id=BID, movement_type=SL.SALE,
                                qty_delta=-15, product_name=name, update_cache=False)
        db.commit()
        assert r1.balance_after == 40.0
        assert r2.balance_after == 25.0
    finally:
        db.close()


# ── cache stays in step + is rebuildable ─────────────────────────────────────

def test_inventory_cache_updates_on_movement():
    name = "Milk Powder 500g"
    _seed_inventory(name, stock=0)
    db = SessionLocal()
    try:
        SL.record_movement(db, business_id=BID, movement_type=SL.PURCHASE,
                           qty_delta=12, product_name=name)
        db.commit()
        inv = db.query(Inventory).filter(Inventory.business_id == BID,
                                         Inventory.product_name == name).first()
        assert inv.stock == 12
    finally:
        db.close()


def test_rebuild_cache_recomputes_from_ledger():
    name = "Wheat Flour 10kg"
    _seed_inventory(name, stock=999)   # deliberately wrong cache
    db = SessionLocal()
    try:
        SL.record_movement(db, business_id=BID, movement_type=SL.PURCHASE,
                           qty_delta=20, product_name=name, update_cache=False)
        SL.record_movement(db, business_id=BID, movement_type=SL.SALE,
                           qty_delta=-5, product_name=name, update_cache=False)
        db.commit()
        updated = SL.rebuild_inventory_cache(db, BID)
        db.commit()
        assert updated >= 1
        inv = db.query(Inventory).filter(Inventory.business_id == BID,
                                         Inventory.product_name == name).first()
        assert inv.stock == 15   # 20 - 5, not the bogus 999
    finally:
        db.close()


# ── append-only: a correction is a NEW row ───────────────────────────────────

def test_correction_is_a_new_row_not_an_edit():
    name = "Coffee Powder 500g"
    db = SessionLocal()
    try:
        SL.record_movement(db, business_id=BID, movement_type=SL.PURCHASE,
                           qty_delta=10, product_name=name, update_cache=False)
        db.commit()
        before = db.query(StockLedger).filter(StockLedger.business_id == BID,
                                              StockLedger.product_name == name).count()
        # fix an over-count with a signed adjustment — a NEW row
        SL.record_movement(db, business_id=BID, movement_type=SL.ADJUSTMENT,
                           qty_delta=-3, product_name=name,
                           note="recount correction", update_cache=False)
        db.commit()
        after = db.query(StockLedger).filter(StockLedger.business_id == BID,
                                             StockLedger.product_name == name).count()
        assert after == before + 1
        assert SL.current_stock(db, BID, product_name=name) == 7.0
    finally:
        db.close()


# ── validation ───────────────────────────────────────────────────────────────

def test_unknown_movement_type_rejected():
    db = SessionLocal()
    try:
        with pytest.raises(ValueError):
            SL.record_movement(db, business_id=BID, movement_type="teleport",
                               qty_delta=1, product_name="X")
    finally:
        db.close()


def test_missing_product_key_rejected():
    db = SessionLocal()
    try:
        with pytest.raises(ValueError):
            SL.record_movement(db, business_id=BID, movement_type=SL.PURCHASE, qty_delta=1)
    finally:
        db.close()
