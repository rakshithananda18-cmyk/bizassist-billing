"""Synthetic migration conflicts: replay, multiplicity, tenant isolation, atomicity."""
import copy
import uuid

import pytest
from sqlalchemy import text

from tests.test_b2b_transfer import net, client
from database.db import SessionLocal, engine
from database.models import Product, Invoice
from core.models import B2BOrder, B2BOrderLineItem


def payload(net):
    tables = client.get('/api/data-transfer/export', headers=net['seller']['headers']).json()['tables']
    return {'tables': {key: copy.deepcopy(tables[key]) for key in ('b2b_orders', 'b2b_order_line_items')}}


def post(net, data):
    return client.post('/api/data-transfer/import', headers=net['seller']['headers'], json=data)


def fresh_order(data, amount=20):
    order = data['tables']['b2b_orders'][0]
    order.update(order_number='FIXTURE-' + uuid.uuid4().hex, uid=str(uuid.uuid4()), total_amount=amount)
    source = data['tables']['b2b_order_line_items'][0]
    lines = []
    for _ in range(2):
        line = dict(source, uid=str(uuid.uuid4()), order_number_ref=order['order_number'],
                    quantity=1, unit_price=10, line_total=10)
        lines.append(line)
    data['tables']['b2b_order_line_items'] = lines
    return order


@pytest.mark.parametrize('preserve_uid', [True, False])
def test_float_round_trip_replay_does_not_append(net, preserve_uid):
    data = payload(net)
    for line in data['tables']['b2b_order_line_items']:
        line['quantity'] += 0.00000001
        line['line_total'] += 0.00000001
        if not preserve_uid:
            line['uid'] = str(uuid.uuid4())
    response = post(net, data)
    assert response.status_code == 200, response.text
    assert response.json()['imported'].get('b2b_order_line_items', 0) == 0


def test_identical_lines_are_a_multiset_and_retry_is_idempotent(net):
    data = payload(net)
    order = fresh_order(data)
    for _ in range(2):
        response = post(net, data)
        assert response.status_code == 200, response.text
    with SessionLocal() as db:
        stored = db.query(B2BOrder).filter_by(order_number=order['order_number']).one()
        assert len(stored.line_items) == 2


def test_conflicting_extra_line_rolls_back_the_entire_import(net):
    data = payload(net)
    line = data['tables']['b2b_order_line_items'][0]
    data['tables']['b2b_order_line_items'] = [dict(line, uid=str(uuid.uuid4()), quantity=9, line_total=9000)]
    marker = 'must-rollback-' + uuid.uuid4().hex
    data['tables']['products'] = [{'name': marker, 'uid': str(uuid.uuid4()), 'business_id': net['seller']['bid']}]
    response = post(net, data)
    assert response.status_code == 409, response.text
    with SessionLocal() as db:
        assert db.query(Product).filter_by(name=marker).first() is None
        stored = db.query(B2BOrder).filter_by(order_number=net['order_number']).one()
        assert len(stored.line_items) == 2


def test_missing_product_cannot_leave_new_header_or_partial_lines(net):
    data = payload(net)
    order = fresh_order(data)
    data['tables']['b2b_order_line_items'][1].update(product_uid='absent', product_name='Absent fixture')
    response = post(net, data)
    assert response.status_code == 409, response.text
    with SessionLocal() as db:
        assert db.query(B2BOrder).filter_by(order_number=order['order_number']).first() is None


def test_new_order_without_children_is_rejected(net):
    data = payload(net)
    order = fresh_order(data)
    data['tables']['b2b_order_line_items'] = []
    assert post(net, data).status_code == 409
    with SessionLocal() as db:
        assert db.query(B2BOrder).filter_by(order_number=order['order_number']).first() is None


def test_existing_uid_with_changed_price_is_not_silently_ignored(net):
    data = payload(net)
    data['tables']['b2b_order_line_items'][0]['unit_price'] += 5
    assert post(net, data).status_code == 409


def test_order_number_cannot_be_repointed_to_another_business_pair(net):
    data = payload(net)
    data['tables']['b2b_orders'][0]['buyer_bizid'] = 'BA-FIXTURE-OTHER'
    response = post(net, data)
    assert response.status_code == 409, response.text


def test_backup_does_not_revert_existing_order_status(net):
    data = payload(net)
    data['tables']['b2b_orders'][0]['status'] = 'pending'
    assert post(net, data).status_code == 200
    with SessionLocal() as db:
        assert db.query(B2BOrder).filter_by(order_number=net['order_number']).one().status == 'completed'


def test_generic_financial_row_rejection_also_rolls_back_the_import(net):
    marker = 'REJECT-' + uuid.uuid4().hex
    data = {'tables': {
        'products': [{'id': 71001, 'uid': str(uuid.uuid4()), 'business_id': net['seller']['bid'], 'name': marker}],
        'invoices': [{'id': 71002, 'uid': str(uuid.uuid4()), 'business_id': net['seller']['bid'],
                      'invoice_id': marker, 'total_amount': 10, 'amount': 10}],
        'invoice_line_items': [{'id': 71003, 'uid': str(uuid.uuid4()), 'invoice_id': 71002,
                               'product_name': 'Overfill fixture', 'quantity': 2, 'unit_price': 10, 'line_total': 20}],
    }}
    response = post(net, data)
    assert response.status_code == 409, response.text
    with SessionLocal() as db:
        assert db.query(Product).filter_by(name=marker).first() is None
        assert db.query(Invoice).filter_by(invoice_id=marker).first() is None


def test_generic_nonfinancial_skips_are_explicit_in_the_response(net):
    data = {'tables': {'godowns': [{'uid': str(uuid.uuid4()), 'business_id': net['seller']['bid'], 'name': None}]}}
    response = post(net, data)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['complete'] is False
    assert result['skipped_records'][0]['table'] == 'godowns'
    assert 'SQL' not in result['skipped_records'][0]['reason']


def test_database_rejection_rolls_back_headers_and_lines(net):
    if engine.dialect.name != 'postgresql':
        pytest.skip('Postgres transaction-abort regression')
    data = payload(net)
    order = fresh_order(data)
    data['tables']['b2b_order_line_items'][1]['product_name'] = 'Reject fixture'
    # Resolve the renamed line by its original seller-scoped product UID.
    with engine.begin() as conn:
        conn.execute(text("""CREATE OR REPLACE FUNCTION reject_fixture_line() RETURNS trigger AS $$
            BEGIN IF NEW.product_name = 'Reject fixture' THEN
              RAISE EXCEPTION 'fixture private driver detail'; END IF; RETURN NEW; END;
            $$ LANGUAGE plpgsql"""))
        conn.execute(text('CREATE TRIGGER reject_fixture_line BEFORE INSERT ON b2b_order_line_items FOR EACH ROW EXECUTE FUNCTION reject_fixture_line()'))
    try:
        response = post(net, data)
        assert response.status_code == 500, response.text
        assert 'private driver detail' not in response.text
        with SessionLocal() as db:
            assert db.query(B2BOrder).filter_by(order_number=order['order_number']).first() is None
    finally:
        with engine.begin() as conn:
            conn.execute(text('DROP TRIGGER reject_fixture_line ON b2b_order_line_items'))
            conn.execute(text('DROP FUNCTION reject_fixture_line()'))
