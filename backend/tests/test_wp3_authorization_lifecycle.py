"""
tests/test_wp3_authorization_lifecycle.py
=========================================
Regression tests for Work Package 3: Authorization & Session Boundaries:
- BD-07: Direct order command denies products outside connection's catalogue category policy
- BD-08: Order state transition graph enforces valid edges and blocks mutation of terminal states
"""
from __future__ import annotations

import pytest
from datetime import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from database.db import Base
from database.models import User, Product, B2BConnection, B2BOrder, B2BOrderLineItem, utc_now
from core.order.service import create_order, transition_order_status


@pytest.fixture
def order_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionMaker = sessionmaker(bind=engine)
    session = SessionMaker()
    try:
        # Seller
        seller = User(
            id=10,
            public_id="BIZ-SELLER-01",
            username="seller_user",
            password="pw",
            role="enterprise",
            business_name="Seller Enterprise"
        )
        # Buyer
        buyer = User(
            id=20,
            public_id="BIZ-BUYER-01",
            username="buyer_user",
            password="pw",
            role="enterprise",
            business_name="Buyer Retail"
        )
        session.add_all([seller, buyer])
        session.commit()
        yield session
    finally:
        session.close()


def test_bd07_direct_order_denies_hidden_catalogue_category(order_db: Session):
    """
    BD-07: Even if a buyer directly specifies the integer product_id of a seller's item,
    create_order must deny items outside the connection's permitted catalog_category.
    """
    seller_id = 10
    buyer_id = 20

    # Connection permits ONLY "Grocery"
    conn = B2BConnection(
        seller_business_id=seller_id,
        buyer_business_id=buyer_id,
        status="accepted",
        catalog_category="Grocery",
        price_tier="standard",
        discount_pct=0.0
    )
    # Permitted item
    p_grocery = Product(
        id=101,
        business_id=seller_id,
        name="Basmati Rice",
        category="Grocery",
        selling_price=100.0,
        is_active=True
    )
    # Hidden item
    p_electronics = Product(
        id=102,
        business_id=seller_id,
        name="Smartphone",
        category="Electronics",
        selling_price=15000.0,
        is_active=True
    )
    order_db.add_all([conn, p_grocery, p_electronics])
    order_db.commit()

    # 1. Ordering permitted item succeeds
    order1 = create_order(
        order_db,
        buyer_business_id=buyer_id,
        seller_business_id=seller_id,
        items=[{"product_id": 101, "quantity": 2.0}]
    )
    assert order1.id is not None
    assert len(order1.line_items) == 1

    # 2. Attempting to directly order hidden item by ID fails
    with pytest.raises(ValueError) as exc_info:
        create_order(
            order_db,
            buyer_business_id=buyer_id,
            seller_business_id=seller_id,
            items=[{"product_id": 102, "quantity": 1.0}]
        )
    assert "not found in supplier catalogue" in str(exc_info.value)


def test_bd08_order_state_transitions_and_terminal_states(order_db: Session):
    """
    BD-08: Order state machine enforces valid edges and blocks mutation of terminal states
    (e.g., completed orders cannot be rejected or cancelled).
    """
    seller_id = 10
    buyer_id = 20

    conn = B2BConnection(
        seller_business_id=seller_id,
        buyer_business_id=buyer_id,
        status="accepted",
        price_tier="standard",
        discount_pct=0.0
    )
    prod = Product(
        id=201,
        business_id=seller_id,
        name="Item A",
        selling_price=50.0,
        is_active=True
    )
    order_db.add_all([conn, prod])
    order_db.commit()

    # Create pending order
    order = create_order(
        order_db,
        buyer_business_id=buyer_id,
        seller_business_id=seller_id,
        items=[{"product_id": 201, "quantity": 1.0}]
    )
    assert order.status == "pending"

    # Pending -> Packed is an invalid edge (must be accepted first)
    with pytest.raises(ValueError) as exc:
        transition_order_status(order_db, seller_id, order.id, "packed")
    assert "Invalid order transition" in str(exc.value)

    # Valid progression: pending -> accepted -> packed -> dispatched
    transition_order_status(order_db, seller_id, order.id, "accepted")
    assert order.status == "accepted"

    transition_order_status(order_db, seller_id, order.id, "packed")
    assert order.status == "packed"

    transition_order_status(order_db, seller_id, order.id, "dispatched")
    assert order.status == "dispatched"

    # Dispatched -> completed (terminal)
    transition_order_status(order_db, seller_id, order.id, "completed")
    assert order.status == "completed"

    # Attempting to reject a completed order MUST fail (BD-08)
    with pytest.raises(ValueError) as exc:
        transition_order_status(order_db, seller_id, order.id, "rejected")
    assert "terminal state 'completed'" in str(exc.value)

    # Attempting to cancel a completed order MUST fail
    with pytest.raises(ValueError) as exc:
        transition_order_status(order_db, buyer_id, order.id, "cancelled")
    assert "terminal state 'completed'" in str(exc.value)
