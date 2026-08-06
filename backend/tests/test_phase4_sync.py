"""
tests/test_phase4_sync.py
=========================
Phase 4 — invoice sync. Completing a B2B order posts it to BOTH businesses,
exactly once:
  • the seller gets a sale invoice and their stock is deducted,
  • the buyer gets an auto stock-in (the goods land in their inventory).

Self-contained (own seller/buyer + connection), so it's order-independent.
"""
import os
import sys
import uuid

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_bizassist.db")
os.environ.setdefault("GROQ_API_KEY", "mock_groq_api_key")

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, backend_path)

import pytest
from fastapi.testclient import TestClient
from main_groq import app
from database.db import SessionLocal
from database.models import User, Product, Invoice, PurchaseInvoice
from core.models import B2BOrder, JournalEntry, StockLedger
from core.stock import ledger as SL

client = TestClient(app)


@pytest.fixture(autouse=True)
def _clear_rate_limit():
    from services.rate_limiter import _ip_window, _upload_window
    _ip_window.clear()
    _upload_window.clear()


def _signup(name):
    uname = f"u_{uuid.uuid4().hex[:8]}"
    r = client.post("/signup", json={"username": uname, "password": "TestPass123!", "business_name": name})
    assert r.status_code == 200, r.text
    b = r.json()
    return {"headers": {"Authorization": f"Bearer {b['token']}"}, "bid": b["id"]}


def _bizid(bid):
    db = SessionLocal()
    try:
        return db.query(User).filter(User.id == bid).first().public_id
    finally:
        db.close()


def _connect(seller, buyer):
    code = client.post("/connections/code", headers=seller["headers"]).json()["code"]
    assert client.post("/connections/redeem", headers=buyer["headers"], json={"code": code}).status_code == 200


def _seed_seller_stock(seller_bid, qty=20):
    db = SessionLocal()
    try:
        p = Product(business_id=seller_bid, name="Sync Widget", selling_price=100.0, cost_price=60.0,
                    cgst_rate=9.0, sgst_rate=9.0, category="General", track_inventory=True, is_active=True)
        db.add(p); db.commit()
        SL.record_movement(db, business_id=seller_bid, movement_type=SL.OPENING, qty_delta=qty,
                           product_id=p.id, product_name=p.name, reference_type="manual", note="opening")
        db.commit()
        return p.id
    finally:
        db.close()


def _seller_stock(seller_bid, pid):
    db = SessionLocal()
    try:
        return SL.current_stock(db, seller_bid, product_id=pid)
    finally:
        db.close()


def _buyer_stock_by_name(buyer_bid, name):
    db = SessionLocal()
    try:
        p = db.query(Product).filter(Product.business_id == buyer_bid, Product.name == name).first()
        return None if not p else SL.current_stock(db, buyer_bid, product_id=p.id)
    finally:
        db.close()


def _place_and_complete(seller, buyer, qty):
    pid = _seed_seller_stock(seller["bid"], qty=20)
    place = client.post("/orders", headers=buyer["headers"],
                        json={"seller_bizid": _bizid(seller["bid"]), "items": [{"product_id": pid, "quantity": qty}]})
    assert place.status_code in (200, 201), place.text
    order_id = place.json()["id"]
    assert client.post(f"/orders/{order_id}/status", headers=seller["headers"], json={"status": "accepted"}).status_code == 200
    done = client.post(f"/orders/{order_id}/status", headers=seller["headers"], json={"status": "completed"})
    assert done.status_code == 200, done.text
    return pid, order_id, place.json()["order_number"]


def test_order_completion_posts_both_sides():
    seller, buyer = _signup("Sync Seller"), _signup("Sync Buyer")
    _connect(seller, buyer)
    pid, order_id, order_number = _place_and_complete(seller, buyer, qty=5)

    # Seller stock deducted (20 → 15) by the auto sale invoice.
    assert _seller_stock(seller["bid"], pid) == 15

    # Seller sale invoice created with the deterministic B2B number, linked to the order.
    db = SessionLocal()
    try:
        inv = db.query(Invoice).filter(
            Invoice.business_id == seller["bid"], Invoice.invoice_id == f"B2B-{order_number}"
        ).first()
        assert inv is not None
        order = db.query(B2BOrder).filter(B2BOrder.id == order_id).first()
        assert order.seller_invoice_id == inv.id
    finally:
        db.close()

    # Buyer auto stock-in: the goods landed in the buyer's inventory.
    assert _buyer_stock_by_name(buyer["bid"], "Sync Widget") == 5

    # A completed B2B receipt is also a normal buyer Purchase Bill/payable;
    # that is what makes it visible in Stock & Purchases without double stock.
    db = SessionLocal()
    try:
        purchase = db.query(PurchaseInvoice).filter(
            PurchaseInvoice.business_id == buyer["bid"],
            PurchaseInvoice.invoice_number == f"B2B-{order_number}",
        ).first()
        assert purchase is not None
        # LOWERCASE, and deliberately so. This asserted "Pending" because that
        # is what the code wrote, not because it was right: the Purchase Bills
        # list buckets on 'pending'/'confirmed', so the capitalised value put
        # every B2B bill in NO tab — invisible in the UI while still driving the
        # supplier's outstanding balance. The test agreed with the defect and so
        # could never catch it. See tests/test_purchase_status_vocabulary.py.
        assert purchase.status == "pending"
        assert purchase.total_amount == inv.total_amount
        assert len(purchase.line_items) == 1
        assert purchase.line_items[0].quantity == 5
        journal = db.query(JournalEntry).filter(
            JournalEntry.business_id == buyer["bid"],
            JournalEntry.source_type == "purchase",
            JournalEntry.source_id == purchase.id,
        ).first()
        assert journal is not None
        assert round(sum(line.debit for line in journal.lines), 2) == round(sum(line.credit for line in journal.lines), 2)
    finally:
        db.close()

    # Buyer-facing B2B output deliberately carries only a posted flag, never
    # the seller's database-local invoice primary key.
    buyer_orders = client.get("/orders?role=buyer", headers=buyer["headers"])
    assert buyer_orders.status_code == 200, buyer_orders.text
    buyer_order = next(o for o in buyer_orders.json() if o["id"] == order_id)
    assert buyer_order["seller_invoice_posted"] is True
    assert buyer_order["seller_invoice_id"] is None
    assert buyer_order["buyer_stock_received"] is True


def test_completion_is_exactly_once():
    seller, buyer = _signup("Once Seller"), _signup("Once Buyer")
    _connect(seller, buyer)
    pid, order_id, _ = _place_and_complete(seller, buyer, qty=4)

    # Re-completing must NOT double-post (idempotent).
    client.post(f"/orders/{order_id}/status", headers=seller["headers"], json={"status": "completed"})

    assert _seller_stock(seller["bid"], pid) == 16            # 20 − 4, not 20 − 8
    assert _buyer_stock_by_name(buyer["bid"], "Sync Widget") == 4   # not 8

    db = SessionLocal()
    try:
        assert db.query(PurchaseInvoice).filter(
            PurchaseInvoice.business_id == buyer["bid"],
        ).count() == 1
    finally:
        db.close()


def test_buyer_can_reconcile_a_missing_legacy_purchase_bill_without_duplicate_stock():
    seller, buyer = _signup("Repair Seller"), _signup("Repair Buyer")
    _connect(seller, buyer)
    _, order_id, order_number = _place_and_complete(seller, buyer, qty=3)

    # Simulate a historical receipt created before B2B purchase bills existed.
    db = SessionLocal()
    try:
        purchase = db.query(PurchaseInvoice).filter(
            PurchaseInvoice.business_id == buyer["bid"],
            PurchaseInvoice.invoice_number == f"B2B-{order_number}",
        ).first()
        journal = db.query(JournalEntry).filter(
            JournalEntry.business_id == buyer["bid"],
            JournalEntry.source_type == "purchase",
            JournalEntry.source_id == purchase.id,
        ).first()
        db.delete(journal)
        db.delete(purchase)
        db.commit()
    finally:
        db.close()


def test_buyer_can_reconcile_legacy_bill_when_no_stock_receipt_link_exists():
    """The financial repair must remain possible for an older completed order
    that predates the B2B stock-ledger reference, and must not invent stock."""
    seller, buyer = _signup("Unlinked Repair Seller"), _signup("Unlinked Repair Buyer")
    _connect(seller, buyer)
    _, order_id, order_number = _place_and_complete(seller, buyer, qty=3)

    db = SessionLocal()
    try:
        purchase = db.query(PurchaseInvoice).filter(
            PurchaseInvoice.business_id == buyer["bid"],
            PurchaseInvoice.invoice_number == f"B2B-{order_number}",
        ).first()
        journal = db.query(JournalEntry).filter(
            JournalEntry.business_id == buyer["bid"],
            JournalEntry.source_type == "purchase",
            JournalEntry.source_id == purchase.id,
        ).first()
        db.delete(journal)
        db.delete(purchase)
        db.query(StockLedger).filter(
            StockLedger.business_id == buyer["bid"],
            StockLedger.reference_type == "b2b_order",
            StockLedger.reference_id == order_id,
        ).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()

    assert _buyer_stock_by_name(buyer["bid"], "Sync Widget") == 0
    repaired = client.post(
        f"/orders/{order_id}/purchase-bill/reconcile", headers=buyer["headers"],
    )
    assert repaired.status_code == 200, repaired.text
    assert repaired.json()["buyer_purchase_invoice_id"] is not None
    assert repaired.json()["buyer_stock_received"] is False
    # The repair posts only Accounts Payable. It never makes a new receipt.
    assert _buyer_stock_by_name(buyer["bid"], "Sync Widget") == 0

    # The counterparty may know the shared order, but cannot create a buyer's
    # payable document or mutate the buyer's financial history.
    forbidden = client.post(
        f"/orders/{order_id}/purchase-bill/reconcile", headers=seller["headers"],
    )
    assert forbidden.status_code == 403, forbidden.text

    repaired = client.post(
        f"/orders/{order_id}/purchase-bill/reconcile", headers=buyer["headers"],
    )
    assert repaired.status_code == 200, repaired.text
    assert repaired.json()["buyer_purchase_invoice_id"] is not None
    assert _buyer_stock_by_name(buyer["bid"], "Sync Widget") == 3

    db = SessionLocal()
    try:
        assert db.query(PurchaseInvoice).filter(
            PurchaseInvoice.business_id == buyer["bid"],
            PurchaseInvoice.invoice_number == f"B2B-{order_number}",
        ).count() == 1
    finally:
        db.close()
