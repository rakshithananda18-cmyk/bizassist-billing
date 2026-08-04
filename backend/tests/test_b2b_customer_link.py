"""
tests/test_b2b_customer_link.py
===============================
A B2B counterparty is a customer to the seller exactly as it is a vendor to the
buyer.

The buyer half always held: `_ensure_buyer_purchase_invoice` resolves a Vendor
and sets `purchase_invoices.supplier_id`. The seller half recorded only
`invoices.customer` (a name) against a NULL `customer_id`, so every B2B sale
fell into the UI's "Other Invoices" bucket (which filters on `NOT customer_id`)
and never reached the buyer's ledger.

Locks both halves, and that repeat orders reuse ONE customer row rather than
growing a duplicate per order.
"""
import os
import sys
import uuid

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_bizassist.db")
os.environ["GROQ_API_KEY"] = "mock_groq_api_key"

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, backend_path)

import pytest
from fastapi.testclient import TestClient
from main_groq import app
from database.db import SessionLocal
from database.models import User, Product, Invoice, PurchaseInvoice, Customer, Vendor
from core.models import B2BConnection, B2BOrder, B2BOrderLineItem
from core.order import service as order_svc

client = TestClient(app)


def _signup(prefix):
    username = f"{prefix}_{uuid.uuid4().hex[:8]}"
    r = client.post("/signup", json={"username": username, "password": "TestPass123!",
                                     "business_name": f"{prefix.title()} Traders"})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _order(db, *, seller_id, buyer_id, product_id):
    order = B2BOrder(buyer_business_id=buyer_id, seller_business_id=seller_id,
                     order_number=f"ORD-TEST-{uuid.uuid4().hex[:6].upper()}",
                     order_date="2026-08-01", status="completed",
                     subtotal=900.0, total_amount=900.0)
    db.add(order)
    db.flush()
    db.add(B2BOrderLineItem(order_id=order.id, product_id=product_id,
                            product_name="Basmati 5kg", quantity=2,
                            unit_price=450, line_total=900))
    db.flush()
    return order


@pytest.fixture
def net():
    seller_id, buyer_id = _signup("bcl_seller"), _signup("bcl_buyer")
    db = SessionLocal()
    try:
        product = Product(business_id=seller_id, name="Basmati 5kg", unit="Bag",
                          selling_price=450, track_inventory=False)
        db.add(product)
        db.add(B2BConnection(seller_business_id=seller_id, buyer_business_id=buyer_id,
                             status="accepted"))
        db.flush()
        yield {"db": db, "seller": seller_id, "buyer": buyer_id, "product": product.id}
    finally:
        db.close()


def test_seller_invoice_links_to_a_customer_row(net):
    db, seller, buyer = net["db"], net["seller"], net["buyer"]
    order = _order(db, seller_id=seller, buyer_id=buyer, product_id=net["product"])

    inv = order_svc.sync_completed_order(db, order)

    assert inv.customer_id is not None, (
        "seller's B2B sale invoice must carry a customer FK, or it lands in "
        "'Other Invoices' and never reaches the buyer's ledger")
    customer = db.query(Customer).filter(Customer.id == inv.customer_id).first()
    assert customer.business_id == seller, "customer row must belong to the SELLER"
    assert customer.name == db.query(User).filter(User.id == buyer).first().business_name


def test_buyer_purchase_bill_links_to_a_vendor_row(net):
    """The mirror half — asserted here so the pair cannot drift apart."""
    db, seller, buyer = net["db"], net["seller"], net["buyer"]
    order = _order(db, seller_id=seller, buyer_id=buyer, product_id=net["product"])

    order_svc.sync_completed_order(db, order)

    bill = db.query(PurchaseInvoice).filter(
        PurchaseInvoice.business_id == buyer,
        PurchaseInvoice.invoice_number == f"B2B-{order.order_number}",
    ).first()
    assert bill is not None and bill.supplier_id is not None
    vendor = db.query(Vendor).filter(Vendor.id == bill.supplier_id).first()
    assert vendor.business_id == buyer, "vendor row must belong to the BUYER"


def test_repeat_orders_reuse_one_customer(net):
    db, seller, buyer = net["db"], net["seller"], net["buyer"]
    first = _order(db, seller_id=seller, buyer_id=buyer, product_id=net["product"])
    second = _order(db, seller_id=seller, buyer_id=buyer, product_id=net["product"])

    inv_a = order_svc.sync_completed_order(db, first)
    inv_b = order_svc.sync_completed_order(db, second)

    # `is not None` first: without it two unlinked invoices both read None and
    # compare equal, so this test passed with the link removed entirely.
    assert inv_a.customer_id is not None
    assert inv_a.customer_id == inv_b.customer_id
    assert db.query(Customer).filter(Customer.business_id == seller).count() == 1
