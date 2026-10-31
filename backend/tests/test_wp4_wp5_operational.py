"""
tests/test_wp4_wp5_operational.py
=================================
Regression tests for Work Packages 4 & 5:
- WEB-09: Sales invoices endpoint supports server-side search and offset pagination
- BD-11: Customer payment endpoint strictly isolates customer receipts and rejects supplier payments (422)
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database.models import Base, User, Invoice, utc_now
from database.db import get_db
from services.auth import get_active_user
from core.api.sales import router as sales_router
from core.api.payments import router as payments_router
from fastapi import FastAPI


@pytest.fixture
def test_app_and_db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    SessionMaker = sessionmaker(bind=engine)
    session = SessionMaker()

    app = FastAPI()

    user = User(
        id=1,
        public_id="BIZ-TEST-OP-01",
        username="op_user",
        password="hashed_pw",
        business_name="Operational Test Business"
    )
    session.add(user)
    session.commit()

    def override_get_db():
        try:
            yield session
        finally:
            pass

    def override_get_active_user():
        return {"id": user.id, "username": user.username, "business_id": user.id}

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_active_user] = override_get_active_user

    app.include_router(sales_router, prefix="/billing")
    app.include_router(payments_router, prefix="/billing")

    client = TestClient(app)
    try:
        yield client, session, user
    finally:
        session.close()


def test_web09_invoices_search_and_pagination(test_app_and_db):
    """WEB-09: Server-side search and pagination allows discovering records without client 500-cap."""
    client, session, user = test_app_and_db

    # Create 10 sample invoices
    for i in range(1, 11):
        inv = Invoice(
            business_id=user.id,
            invoice_id=f"INV-2026-{i:03d}",
            customer=f"Customer {'Alpha' if i % 2 == 0 else 'Beta'}",
            invoice_date="2026-10-30",
            total_amount=100.0 * i,
            status="unpaid"
        )
        session.add(inv)
    session.commit()

    # 1. Pagination: per_page=3, page=1
    r1 = client.get("/billing/invoices?per_page=3&page=1")
    assert r1.status_code == 200
    data1 = r1.json()
    assert len(data1) == 3

    # 2. Pagination: per_page=3, page=2
    r2 = client.get("/billing/invoices?per_page=3&page=2")
    assert r2.status_code == 200
    data2 = r2.json()
    assert len(data2) == 3
    # Distinct records across pages
    ids1 = {d["invoice_no"] for d in data1}
    ids2 = {d["invoice_no"] for d in data2}
    assert ids1.isdisjoint(ids2)

    # 3. Server Search by customer name
    r3 = client.get("/billing/invoices?search=Alpha")
    assert r3.status_code == 200
    data3 = r3.json()
    assert len(data3) == 5
    assert all("Alpha" in d["customer_name"] for d in data3)

    # 4. Server Search by invoice number
    r4 = client.get("/billing/invoices?search=INV-2026-007")
    assert r4.status_code == 200
    data4 = r4.json()
    assert len(data4) == 1
    assert data4[0]["invoice_no"] == "INV-2026-007"


def test_bd11_supplier_payment_boundary(test_app_and_db):
    """BD-11: Customer payment receipt endpoint explicitly rejects supplier payments."""
    client, session, user = test_app_and_db

    payload = {
        "type": "supplier_payment",
        "amount": 500.0,
        "method": "Cash",
        "date": "2026-10-30",
        "idempotency_key": "supp-pay-001"
    }
    r = client.post("/billing/payments", json=payload)
    assert r.status_code == 422
    assert "Supplier payments require a purchase-payment workflow" in r.text
