from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import core.models  # noqa: F401 — complete Billing metadata
from database.models import Base, Invoice, InvoiceLineItem, User
from services import insights_service


@pytest.fixture
def charts_db():
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add_all([User(id=1, username='chart-owner', password='dummy'), User(id=2, username='other-owner', password='dummy')])
        db.commit()
        yield db
    engine.dispose()


def test_charts_use_current_totals_partial_dues_returns_and_tenant_scope(charts_db, monkeypatch):
    monkeypatch.setattr(insights_service, 'biz_now', lambda: datetime(2026, 10, 28, 12))
    rows = [
        Invoice(id=1, business_id=1, invoice_id='SALE', invoice_date='2026-10-20', due_date='2026-10-21',
                amount=5, total_amount=1000, paid_amount=700, status='Partial'),
        Invoice(id=2, business_id=1, invoice_id='RETURN', invoice_date='2026-10-21', due_date='2026-10-21',
                total_amount=200, paid_amount=0, invoice_type='credit_note', status='Pending'),
        Invoice(id=3, business_id=2, invoice_id='OTHER', invoice_date='2026-10-20', due_date='2026-10-21',
                total_amount=9000, paid_amount=0, status='Pending'),
        Invoice(id=4, business_id=1, invoice_id='VOID', invoice_date='2026-10-20', due_date='2026-10-21',
                total_amount=5000, paid_amount=0, status='Cancelled'),
    ]
    charts_db.add_all(rows)
    charts_db.flush()
    charts_db.add_all([
        InvoiceLineItem(invoice_id=1, product_name='Widget', quantity=1, unit_price=600, line_total=600),
        InvoiceLineItem(invoice_id=1, product_name='Gadget', quantity=1, unit_price=400, line_total=400),
        InvoiceLineItem(invoice_id=2, product_name='Widget', quantity=1, unit_price=200, line_total=200),
    ])
    charts_db.commit()
    result = insights_service.dashboard_charts(1, charts_db)
    assert result['monthly_revenue'] == [{'month': 'Oct 26', 'revenue': 800}]
    assert sum(row['amount'] for row in result['aging_overview']) == 300
    assert {row['name']: row['value'] for row in result['top_products']} == {'Widget': 400, 'Gadget': 400}


def test_zero_total_is_authoritative_and_not_replaced_by_legacy_amount(charts_db, monkeypatch):
    monkeypatch.setattr(insights_service, 'biz_now', lambda: datetime(2026, 10, 28, 12))
    charts_db.add(Invoice(business_id=1, invoice_id='FREE', invoice_date='2026-10-20', due_date='2026-10-21',
                         total_amount=0, amount=99, paid_amount=0, status='Pending'))
    charts_db.commit()
    result = insights_service.dashboard_charts(1, charts_db)
    assert result['monthly_revenue'][0]['revenue'] == 0
    assert sum(row['amount'] for row in result['aging_overview']) == 0
