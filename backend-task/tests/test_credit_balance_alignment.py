"""Field planning/collections use Billing's linked-credit-adjusted obligation."""
import os

import pytest

from app.billing_models import BillingInvoice, BillingInvoicePayment
from app.db import SessionLocal
from app.invoices import invoice_balances
from app.models import FieldTask
from app.timeutil import biz_today
from tests.conftest import check_in, geo
from tests.test_billing_invoices import _bill, _customer


def fixture_bill(client, biz, *, total=100, paid=0):
    customer = _customer(biz.business_id, 'Credit alignment fixture')
    shop = client.post('/api/shops/import-billing', headers=biz.h, json={'customer_ids': [customer]}).json()['created'][0]
    invoice_id = _bill(biz.business_id, customer, 'CREDIT-ALIGNMENT', total=total, paid=paid)
    return shop, invoice_id


def credit(biz, invoice_id, amount):
    with SessionLocal() as db:
        source = db.get(BillingInvoice, invoice_id)
        db.add(BillingInvoice(business_id=biz.business_id, customer_id=source.customer_id,
            invoice_id='RETURN-' + str(invoice_id), invoice_type='credit_note', parent_invoice_id=invoice_id,
            amount=amount, total_amount=amount, paid_amount=0, invoice_date=biz_today(), status='Paid'))
        db.commit()


def plan(client, biz, staff_id, shop, invoice_id, task_type='payment_collect'):
    return client.post('/api/tasks', headers=biz.h, json={
        'title': 'Credit-adjusted fixture', 'staff_id': staff_id, 'shop_id': shop['id'],
        'task_type': task_type, 'invoice_ids': [invoice_id],
    })


def test_unpaid_fully_returned_bill_cannot_be_planned_or_collected(client, biz):
    shop, invoice_id = fixture_bill(client, biz)
    credit(biz, invoice_id, 100)
    staff = biz.staff()
    rows = client.get(f"/api/shops/{shop['id']}/billing-invoices", headers=biz.h).json()['invoices']
    assert not any(invoice['id'] == invoice_id for invoice in rows)
    for kind in ('delivery', 'payment_collect'):
        response = plan(client, biz, staff['id'], shop, invoice_id, kind)
        assert response.status_code == 409, response.text


def test_partial_return_reduces_expected_and_current_collection_amount(client, biz):
    shop, invoice_id = fixture_bill(client, biz)
    credit(biz, invoice_id, 40)
    staff = biz.staff()
    response = plan(client, biz, staff['id'], shop, invoice_id)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body['amount_expected'] == body['current_amount_due'] == 60
    assert body['invoices'][0]['balance_due'] == 60
    assert body['invoices'][0]['current_credited'] == 40


def test_return_after_assignment_prevents_positive_collection(client, biz):
    shop, invoice_id = fixture_bill(client, biz)
    staff, headers = biz.staff_session()
    response = plan(client, biz, staff['id'], shop, invoice_id)
    assert response.status_code == 201, response.text
    task_id = response.json()['id']
    credit(biz, invoice_id, 100)
    check_in(client, headers)
    response = client.post(f'/api/tasks/{task_id}/complete', headers=headers,
                           json={'geo': geo(), 'amount_collected': 1})
    assert response.status_code == 409, response.text
    with SessionLocal() as db:
        saved = db.get(FieldTask, task_id)
        assert saved.status == 'pending' and saved.amount_collected is None


def test_paid_return_exposes_credit_due_without_a_collectible_amount(client, biz):
    shop, invoice_id = fixture_bill(client, biz, paid=100)
    credit(biz, invoice_id, 40)
    rows = client.get(f"/api/shops/{shop['id']}/billing-invoices", headers=biz.h).json()['invoices']
    invoice = next(invoice for invoice in rows if invoice['id'] == invoice_id)
    assert invoice['balance_due'] == 0 and invoice['credit_due'] == 40
    staff = biz.staff()
    assert plan(client, biz, staff['id'], shop, invoice_id).status_code == 409


def test_actual_receipt_sum_is_authoritative_and_matches_billing_helper(client, biz):
    shop, invoice_id = fixture_bill(client, biz, paid=5)
    credit(biz, invoice_id, 20)
    with SessionLocal() as db:
        invoice = db.get(BillingInvoice, invoice_id)
        db.add(BillingInvoicePayment(business_id=biz.business_id, invoice_id=invoice_id,
            amount_paid=30, payment_mode='Cash', payment_date=biz_today()))
        db.commit()
        projection = invoice_balances(db, [invoice])[invoice_id]
        assert projection['outstanding'] == 50 and projection['paid'] == 30
        if os.getenv('BILLING_BACKEND_DIR'):
            from core.billing.balances import invoice_balances as billing_balances
            assert projection == billing_balances(db, [invoice])[invoice_id]
