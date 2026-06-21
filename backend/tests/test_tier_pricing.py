"""
tests/test_tier_pricing.py
==========================
Gate-1 coverage for B2B TIER PRICING on the ORDER path (the catalog path is
already covered in test_connections.py). Proves `create_order` resolves the
buyer's unit price from the connection's `price_tier` BEFORE applying
`discount_pct`, and that a missing/zero tier column falls back to selling_price
(a seller who hasn't set tier prices still trades at retail, never free).

Self-contained: creates its own seller/buyer + connection + products, so it
does not depend on test ordering. Calls the service functions directly to pin
the pricing math precisely (no HTTP plumbing).
"""
import os
import sys
import uuid

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_bizassist.db")
os.environ.setdefault("GROQ_API_KEY", "mock_groq_api_key")

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, backend_path)

import pytest
from main_groq import app  # noqa: F401  (import builds metadata / test DB columns)
from database.db import SessionLocal
from database.models import User, Product, Inventory
from core.models import B2BConnection
from core.order import service


def _mk_user(db, name):
    u = User(
        username=f"u_{uuid.uuid4().hex[:8]}",
        password="x",
        business_name=name,
        public_id=uuid.uuid4().hex[:12],
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _mk_connection(db, seller_id, buyer_id, *, price_tier, discount_pct):
    conn = B2BConnection(
        seller_business_id=seller_id,
        buyer_business_id=buyer_id,
        status="accepted",
        price_tier=price_tier,
        discount_pct=discount_pct,
        stock_visibility="exact",
    )
    db.add(conn)
    db.commit()
    db.refresh(conn)
    return conn


def _mk_product(db, seller_id, **prices):
    p = Product(
        business_id=seller_id,
        name=f"Item-{uuid.uuid4().hex[:6]}",
        is_active=True,
        category="Medicines",
        **prices,
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    db.add(Inventory(business_id=seller_id, product_id=p.id, stock=100))
    db.commit()
    return p


def _make(db, *, price_tier, discount_pct, **prices):
    seller, buyer = _mk_user(db, "TierSeller"), _mk_user(db, "TierBuyer")
    conn = _mk_connection(db, seller.id, buyer.id,
                          price_tier=price_tier, discount_pct=discount_pct)
    p = _mk_product(db, seller.id, **prices)
    return seller, buyer, conn, p


def test_order_uses_wholesale_tier_then_discount():
    db = SessionLocal()
    try:
        seller, buyer, _, p = _make(
            db, price_tier="wholesale", discount_pct=10.0,
            selling_price=100.0, wholesale_price=80.0, distributor_price=70.0,
        )
        order = service.create_order(db, buyer.id, seller.id,
                                     [{"product_id": p.id, "quantity": 5.0}])
        li = order.line_items[0]
        # 80 (wholesale) * 0.90 (10% off) = 72.0
        assert round(li.unit_price, 2) == 72.0
        assert round(order.subtotal, 2) == 360.0  # 72 * 5
    finally:
        db.close()


def test_order_uses_distributor_tier_then_discount():
    db = SessionLocal()
    try:
        seller, buyer, _, p = _make(
            db, price_tier="distributor", discount_pct=5.0,
            selling_price=100.0, wholesale_price=80.0, distributor_price=70.0,
        )
        order = service.create_order(db, buyer.id, seller.id,
                                     [{"product_id": p.id, "quantity": 2.0}])
        # 70 (distributor) * 0.95 (5% off) = 66.5
        assert round(order.line_items[0].unit_price, 2) == 66.5
    finally:
        db.close()


def test_order_tier_falls_back_to_selling_when_tier_price_zero():
    """wholesale tier but wholesale_price unset(0.0) -> retail selling_price, NOT free."""
    db = SessionLocal()
    try:
        seller, buyer, _, p = _make(
            db, price_tier="wholesale", discount_pct=0.0,
            selling_price=100.0, wholesale_price=0.0, distributor_price=0.0,
        )
        order = service.create_order(db, buyer.id, seller.id,
                                     [{"product_id": p.id, "quantity": 1.0}])
        assert round(order.line_items[0].unit_price, 2) == 100.0
    finally:
        db.close()


def test_catalog_distributor_falls_back_to_wholesale_when_distributor_zero():
    """distributor tier with no distributor_price chains down to wholesale_price."""
    db = SessionLocal()
    try:
        seller, buyer, _, p = _make(
            db, price_tier="distributor", discount_pct=0.0,
            selling_price=100.0, wholesale_price=80.0, distributor_price=0.0,
        )
        catalog = service.get_supplier_catalog(db, buyer.id, seller.id)
        item = next(it for it in catalog if it["product_id"] == p.id)
        assert round(item["selling_price"], 2) == 80.0  # fell back to wholesale
    finally:
        db.close()
