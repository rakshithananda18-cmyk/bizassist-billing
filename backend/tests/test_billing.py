"""
tests/test_billing.py
=====================
The first money command — `create_sale_invoice`. Locks in:
  • deterministic GST: intra-state (CGST+SGST) vs inter-state (IGST)
  • tax-inclusive (MRP) back-calculation
  • multi-line totals + round-off
  • stock deducted through the append-only ledger (one SALE movement per line)
  • non-stock items (track_inventory=False) skip stock
  • idempotency: same invoice number → no double-post, stock deducted once
  • status derived from paid_amount (Paid / Partial / Pending)
  • atomicity: header + lines + stock committed together

Pure DB unit test.
"""
import os
import sys

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_bizassist.db")
os.environ.setdefault("GROQ_API_KEY", "mock_groq_api_key")

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, backend_path)

import pytest
from database.db import SessionLocal
from database.models import Base, Product, Invoice, InvoiceLineItem, Inventory, User
from core.models import StockLedger
from core.billing import commands as billing
from core.stock import ledger as SL

BID = 700700


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
        db.query(StockLedger).filter(StockLedger.business_id == BID).delete()
        db.query(Inventory).filter(Inventory.business_id == BID).delete()
        db.query(Product).filter(Product.business_id == BID).delete()
        db.query(User).filter(User.id == BID).delete()
        db.commit()
    finally:
        db.close()


def _setup_business(state="29"):
    db = SessionLocal()
    try:
        db.add(User(id=BID, username=f"biz{BID}", password="x", state_code=state))
        db.commit()
    finally:
        db.close()


def _product(name, *, cgst=9.0, sgst=9.0, igst=18.0, track=True, stock=100):
    db = SessionLocal()
    try:
        p = Product(business_id=BID, name=name, hsn_sac="1006", unit="Nos",
                    cgst_rate=cgst, sgst_rate=sgst, igst_rate=igst, track_inventory=track)
        db.add(p)
        db.flush()
        db.add(Inventory(business_id=BID, product_name=name, product_id=p.id, stock=stock))
        # seed opening stock as a ledger movement so current_stock is meaningful
        SL.record_movement(db, business_id=BID, movement_type=SL.OPENING,
                           qty_delta=stock, product_id=p.id, product_name=name, update_cache=False)
        db.commit()
        return p.id
    finally:
        db.close()


@pytest.fixture(autouse=True)
def _setup():
    _ensure_schema()
    _clear()
    _setup_business()
    yield
    _clear()


# ── GST: intra vs inter ──────────────────────────────────────────────────────

def test_intra_state_splits_cgst_sgst():
    pid = _product("Rice")
    db = SessionLocal()
    try:
        inv = billing.create_sale_invoice(
            db, business_id=BID, place_of_supply="29-Karnataka", paid_amount=236,
            lines=[{"product_id": pid, "quantity": 2, "unit_price": 100}])
        assert inv.subtotal == 200.0
        assert inv.cgst_total == 18.0 and inv.sgst_total == 18.0 and inv.igst_total == 0.0
        assert inv.total_amount == 236.0
        assert inv.status == "Paid"
    finally:
        db.close()


def test_inter_state_uses_igst():
    pid = _product("Rice")
    db = SessionLocal()
    try:
        inv = billing.create_sale_invoice(
            db, business_id=BID, place_of_supply="27-Maharashtra",
            lines=[{"product_id": pid, "quantity": 2, "unit_price": 100}])
        assert inv.igst_total == 36.0 and inv.cgst_total == 0.0 and inv.sgst_total == 0.0
        assert inv.total_amount == 236.0
    finally:
        db.close()


def test_tax_inclusive_backcalculates():
    pid = _product("MRP Item")
    db = SessionLocal()
    try:
        inv = billing.create_sale_invoice(
            db, business_id=BID, place_of_supply="29", tax_inclusive=True,
            lines=[{"product_id": pid, "quantity": 1, "unit_price": 118}])
        assert inv.subtotal == 100.0
        assert inv.cgst_total == 9.0 and inv.sgst_total == 9.0
        assert inv.total_amount == 118.0
    finally:
        db.close()


# ── Bill-level (whole-invoice) discount ──────────────────────────────────────

def test_bill_discount_apportions_and_taxes_net():
    """A flat ₹ bill discount reduces the taxable base and the GST proportionally,
    and is recorded in discount_total; line items stay consistent with the header."""
    pid = _product("Rice")  # cgst 9 + sgst 9 = 18%, intra
    db = SessionLocal()
    try:
        # 2 × 100 = 200 taxable. With ₹20 off → 180 taxable, 18% GST = 32.4, grand ≈ 212.
        inv = billing.create_sale_invoice(
            db, business_id=BID, place_of_supply="29-Karnataka", bill_discount=20,
            lines=[{"product_id": pid, "quantity": 2, "unit_price": 100}])
        assert inv.subtotal == 180.0
        assert inv.discount_total == 20.0
        assert inv.cgst_total == 16.2 and inv.sgst_total == 16.2
        assert inv.total_amount == 212.0
        # line item carries the apportioned discount + reduced taxable
        line = inv.line_items[0]
        assert line.discount == 20.0 and line.taxable_value == 180.0
    finally:
        db.close()


def test_bill_discount_capped_at_subtotal():
    """A discount larger than the bill is clamped to the subtotal (never negative)."""
    pid = _product("Rice")
    db = SessionLocal()
    try:
        inv = billing.create_sale_invoice(
            db, business_id=BID, place_of_supply="29", bill_discount=500,
            lines=[{"product_id": pid, "quantity": 2, "unit_price": 100}])
        assert inv.subtotal == 0.0
        assert inv.discount_total == 200.0
        assert inv.total_amount == 0.0
    finally:
        db.close()


# ── Stock ────────────────────────────────────────────────────────────────────

def test_sale_deducts_stock_via_ledger():
    pid = _product("Rice", stock=100)
    db = SessionLocal()
    try:
        billing.create_sale_invoice(
            db, business_id=BID, place_of_supply="29",
            lines=[{"product_id": pid, "quantity": 3, "unit_price": 100}])
        assert SL.current_stock(db, BID, product_id=pid) == 97.0   # 100 opening - 3 sold
        mv = db.query(StockLedger).filter(StockLedger.business_id == BID,
                                          StockLedger.movement_type == SL.SALE).all()
        assert len(mv) == 1 and mv[0].qty_delta == -3.0 and mv[0].reference_type == "invoice"
    finally:
        db.close()


def test_non_stock_item_skips_stock():
    pid = _product("Tailoring", track=False, stock=0)
    db = SessionLocal()
    try:
        billing.create_sale_invoice(
            db, business_id=BID, place_of_supply="29",
            lines=[{"product_id": pid, "quantity": 1, "unit_price": 500}])
        sales = db.query(StockLedger).filter(StockLedger.business_id == BID,
                                             StockLedger.movement_type == SL.SALE).count()
        assert sales == 0   # a service never moves stock
    finally:
        db.close()


# ── Idempotency + status + multi-line ────────────────────────────────────────

def test_idempotent_same_invoice_number():
    pid = _product("Rice", stock=100)
    db = SessionLocal()
    try:
        a = billing.create_sale_invoice(
            db, business_id=BID, invoice_no="INV-9", place_of_supply="29",
            lines=[{"product_id": pid, "quantity": 5, "unit_price": 100}])
        b = billing.create_sale_invoice(
            db, business_id=BID, invoice_no="INV-9", place_of_supply="29",
            lines=[{"product_id": pid, "quantity": 5, "unit_price": 100}])
        assert a.id == b.id                                   # same invoice returned
        assert db.query(Invoice).filter(Invoice.business_id == BID,
                                        Invoice.invoice_id == "INV-9").count() == 1
        assert SL.current_stock(db, BID, product_id=pid) == 95.0   # deducted ONCE
    finally:
        db.close()


def test_status_from_paid_amount():
    pid = _product("Rice")
    db = SessionLocal()
    try:
        unpaid = billing.create_sale_invoice(
            db, business_id=BID, invoice_no="U1", place_of_supply="29", paid_amount=0,
            lines=[{"product_id": pid, "quantity": 1, "unit_price": 100}])
        partial = billing.create_sale_invoice(
            db, business_id=BID, invoice_no="U2", place_of_supply="29", paid_amount=50,
            lines=[{"product_id": pid, "quantity": 1, "unit_price": 100}])
        assert unpaid.status == "Pending"
        assert partial.status == "Partial"
    finally:
        db.close()


def test_multi_line_totals_and_autonumber():
    p1 = _product("Rice")
    p2 = _product("Dal")
    db = SessionLocal()
    try:
        inv = billing.create_sale_invoice(
            db, business_id=BID, place_of_supply="29",
            lines=[{"product_id": p1, "quantity": 1, "unit_price": 100},
                   {"product_id": p2, "quantity": 2, "unit_price": 50}])
        assert inv.subtotal == 200.0                 # 100 + 100
        assert inv.invoice_id.startswith("INV-")     # auto-generated number
        items = db.query(InvoiceLineItem).filter(InvoiceLineItem.invoice_id == inv.id).count()
        assert items == 2
    finally:
        db.close()


# ── Multi-terminal POS: per-counter invoice numbering (plan §9.3) ───────────
# Two counters must mint numbers in SEPARATE series so a second terminal can
# never collide with — and get silently merged into — another's sale.

def test_counter_prefix_separates_series():
    pid = _product("Rice", stock=100)
    db = SessionLocal()
    try:
        c1 = billing.create_sale_invoice(
            db, business_id=BID, place_of_supply="29", counter_prefix="C1",
            lines=[{"product_id": pid, "quantity": 1, "unit_price": 100}])
        c2 = billing.create_sale_invoice(
            db, business_id=BID, place_of_supply="29", counter_prefix="C2",
            lines=[{"product_id": pid, "quantity": 1, "unit_price": 100}])
        c1b = billing.create_sale_invoice(
            db, business_id=BID, place_of_supply="29", counter_prefix="C1",
            lines=[{"product_id": pid, "quantity": 1, "unit_price": 100}])
        # each counter has its OWN series, both starting at 0001
        assert c1.invoice_id == "C1-0001"
        assert c2.invoice_id == "C2-0001"
        assert c1b.invoice_id == "C1-0002"        # C1 advances independently of C2
        # three DISTINCT invoices — nothing merged away
        assert len({c1.id, c2.id, c1b.id}) == 3
    finally:
        db.close()


def test_two_counters_first_sale_no_collision():
    """The exact soak bug: two terminals' first sale must NOT collapse into one."""
    pid = _product("Rice", stock=100)
    db = SessionLocal()
    try:
        a = billing.create_sale_invoice(
            db, business_id=BID, place_of_supply="29", counter_prefix="C1",
            lines=[{"product_id": pid, "quantity": 1, "unit_price": 100}])
        b = billing.create_sale_invoice(
            db, business_id=BID, place_of_supply="29", counter_prefix="C2",
            lines=[{"product_id": pid, "quantity": 1, "unit_price": 100}])
        assert a.id != b.id and a.invoice_id != b.invoice_id
        assert db.query(Invoice).filter(Invoice.business_id == BID).count() == 2
        assert SL.current_stock(db, BID, product_id=pid) == 98.0   # both deducted
    finally:
        db.close()


def test_blank_prefix_defaults_to_inv_series():
    pid = _product("Rice")
    db = SessionLocal()
    try:
        assert billing._next_invoice_number(db, BID) == "INV-0001"
        assert billing._next_invoice_number(db, BID, "C1") == "C1-0001"
        # trailing '-' is tolerated / normalised
        assert billing._next_invoice_number(db, BID, "C2-") == "C2-0001"
    finally:
        db.close()


# ── Re-number on concurrent collision (§9.3b) — never silently merge ─────────

def test_renumber_on_conflict_creates_distinct_bill():
    pid = _product("Rice", stock=100)
    db = SessionLocal()
    try:
        a = billing.create_sale_invoice(
            db, business_id=BID, invoice_no="C1-0005", place_of_supply="29",
            lines=[{"product_id": pid, "quantity": 1, "unit_price": 100}])
        # A DIFFERENT sale asks for the same number with renumber_on_conflict set
        # (the request-id wall already absorbs true retries) → reassign, don't merge.
        b = billing.create_sale_invoice(
            db, business_id=BID, invoice_no="C1-0005", place_of_supply="29",
            renumber_on_conflict=True,
            lines=[{"product_id": pid, "quantity": 2, "unit_price": 100}])
        assert a.invoice_id == "C1-0005"
        assert b.invoice_id != "C1-0005"          # reassigned
        assert b.invoice_id.startswith("C1-")     # same series, next free slot
        assert a.id != b.id                        # two distinct bills — none lost
        assert SL.current_stock(db, BID, product_id=pid) == 97.0   # 1 + 2 deducted
    finally:
        db.close()


def test_renumber_preserves_lcl_series_prefix():
    pid = _product("Rice", stock=100)
    db = SessionLocal()
    try:
        billing.create_sale_invoice(
            db, business_id=BID, invoice_no="LCL-C1-0005", place_of_supply="29",
            lines=[{"product_id": pid, "quantity": 1, "unit_price": 100}])
        b = billing.create_sale_invoice(
            db, business_id=BID, invoice_no="LCL-C1-0005", place_of_supply="29",
            renumber_on_conflict=True,
            lines=[{"product_id": pid, "quantity": 1, "unit_price": 100}])
        assert b.invoice_id.startswith("LCL-C1-") and b.invoice_id != "LCL-C1-0005"
    finally:
        db.close()


def test_default_still_idempotent_on_duplicate_number():
    pid = _product("Rice", stock=100)
    db = SessionLocal()
    try:
        a = billing.create_sale_invoice(
            db, business_id=BID, invoice_no="C1-0009", place_of_supply="29",
            lines=[{"product_id": pid, "quantity": 1, "unit_price": 100}])
        # No renumber flag (legacy / no request-id) → idempotent return, as before.
        b = billing.create_sale_invoice(
            db, business_id=BID, invoice_no="C1-0009", place_of_supply="29",
            lines=[{"product_id": pid, "quantity": 1, "unit_price": 100}])
        assert a.id == b.id
        assert db.query(Invoice).filter(
            Invoice.business_id == BID, Invoice.invoice_id == "C1-0009").count() == 1
    finally:
        db.close()
