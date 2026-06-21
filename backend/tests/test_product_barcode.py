"""
tests/test_product_barcode.py
=============================
One product → MANY barcodes (companies keep updating packaging). Locks in:
  • a product can hold several codes; each resolves to it
  • adding a new code to a known product is conflict-safe + idempotent
  • a code already on ANOTHER product raises (never silently stolen)
  • exactly one primary; primary mirrors to Product.barcode
  • retired codes still resolve (history kept) only if reactivated; legacy fallback
"""
import os
import sys

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_bizassist.db")
os.environ.setdefault("GROQ_API_KEY", "mock_groq_api_key")

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, backend_path)

import pytest
from database.db import SessionLocal
from database.models import Base, Product
from core.models import ProductBarcode
from core.catalog import barcode as PB

BID = 880002


def _ensure_schema():
    db = SessionLocal()
    try:
        Base.metadata.create_all(bind=db.get_bind())
    finally:
        db.close()


def _clear():
    db = SessionLocal()
    try:
        db.query(ProductBarcode).filter(ProductBarcode.business_id == BID).delete()
        db.query(Product).filter(Product.business_id == BID).delete()
        db.commit()
    finally:
        db.close()


def _product(name):
    db = SessionLocal()
    try:
        p = Product(business_id=BID, name=name)
        db.add(p)
        db.commit()
        return p.id
    finally:
        db.close()


@pytest.fixture(autouse=True)
def _setup():
    _ensure_schema()
    _clear()
    yield
    _clear()


def test_multiple_barcodes_resolve_to_same_product():
    pid = _product("Maggi 70g")
    db = SessionLocal()
    try:
        PB.add_barcode(db, BID, pid, "8901030", source="manual")   # old pack
        PB.add_barcode(db, BID, pid, "8901999", source="scan")     # new carton
        db.commit()
        assert PB.resolve_barcode(db, BID, "8901030").id == pid
        assert PB.resolve_barcode(db, BID, "8901999").id == pid
    finally:
        db.close()


def test_first_barcode_is_primary_and_mirrors_to_product():
    pid = _product("Lays 52g")
    db = SessionLocal()
    try:
        PB.add_barcode(db, BID, pid, "1111", source="manual")
        PB.add_barcode(db, BID, pid, "2222", source="scan")
        db.commit()
        codes = PB.list_barcodes(db, BID, pid)
        primaries = [c for c in codes if c.is_primary]
        assert len(primaries) == 1 and primaries[0].barcode == "1111"
        p = db.query(Product).filter(Product.id == pid).first()
        assert p.barcode == "1111"
    finally:
        db.close()


def test_set_primary_switches_and_mirrors():
    pid = _product("Colgate 100g")
    db = SessionLocal()
    try:
        PB.add_barcode(db, BID, pid, "AAA")
        PB.add_barcode(db, BID, pid, "BBB")
        PB.set_primary(db, BID, pid, "BBB")
        db.commit()
        codes = {c.barcode: c.is_primary for c in PB.list_barcodes(db, BID, pid)}
        assert codes["BBB"] is True and codes["AAA"] is False
        assert db.query(Product).filter(Product.id == pid).first().barcode == "BBB"
    finally:
        db.close()


def test_same_code_same_product_is_idempotent():
    pid = _product("Dairy Milk")
    db = SessionLocal()
    try:
        PB.add_barcode(db, BID, pid, "DUP")
        PB.add_barcode(db, BID, pid, "DUP")   # again
        db.commit()
        rows = db.query(ProductBarcode).filter(ProductBarcode.business_id == BID,
                                               ProductBarcode.barcode == "DUP").all()
        assert len(rows) == 1
    finally:
        db.close()


def test_code_on_another_product_raises_conflict():
    p1 = _product("Item A")
    p2 = _product("Item B")
    db = SessionLocal()
    try:
        PB.add_barcode(db, BID, p1, "SHARED")
        db.commit()
        with pytest.raises(PB.BarcodeConflict):
            PB.add_barcode(db, BID, p2, "SHARED")
    finally:
        db.close()


def test_deactivated_code_stops_resolving_until_reactivated():
    pid = _product("Old Stock Item")
    db = SessionLocal()
    try:
        PB.add_barcode(db, BID, pid, "RETIRE")
        db.commit()
        PB.deactivate(db, BID, "RETIRE")
        db.commit()
        assert PB.resolve_barcode(db, BID, "RETIRE") is None
        # adding it again reactivates (same product)
        PB.add_barcode(db, BID, pid, "RETIRE")
        db.commit()
        assert PB.resolve_barcode(db, BID, "RETIRE").id == pid
    finally:
        db.close()


def test_legacy_product_barcode_still_resolves():
    """A product created before the multi-barcode table (single Product.barcode)
    must still scan."""
    db = SessionLocal()
    try:
        p = Product(business_id=BID, name="Legacy Item", barcode="LEGACY1")
        db.add(p)
        db.commit()
        assert PB.resolve_barcode(db, BID, "LEGACY1").name == "Legacy Item"
    finally:
        db.close()
