"""Shared cloud deletion clears one Field tree and preserves other businesses."""
import os
import sys
from types import ModuleType

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app.billing_models import BillingUser
from app.db import Base, SessionLocal
from app.models import FieldTask
from tests.conftest import Biz, check_in, geo
from tests.test_billing_invoices import _bill, _customer
from tests.test_runs_tasks import _plan

pytestmark = pytest.mark.skipif(
    os.getenv('TASK_TEST_BILLING_SCHEMA') != 'external' or not os.getenv('BILLING_BACKEND_DIR'),
    reason='Requires dedicated database prepared from actual Billing models',
)


def billing_admin(monkeypatch):
    # Synthetic database IDs may coincide with real Chroma namespaces. Never
    # touch the developer's vector store while exercising the database purge.
    embeddings = ModuleType('services.embeddings')
    embeddings.delete_user_chroma_memories = lambda _business: None
    monkeypatch.setitem(sys.modules, 'services.embeddings', embeddings)
    from services import admin_service
    return admin_service


def counts(db, business_id):
    return {table.name: db.scalar(select(func.count()).select_from(table).where(table.c.business_id == business_id))
            for table in Base.metadata.tables.values() if table.name.startswith('ft_')}


def test_cloud_wipe_removes_the_whole_field_tree_only_for_that_business(client, biz, monkeypatch):
    staff, headers = biz.staff_session()
    customer = _customer(biz.business_id, 'Delete lifecycle fixture')
    invoice = _bill(biz.business_id, customer, 'DELETE-FIXTURE', total=50)
    shop = client.post('/api/shops/import-billing', headers=biz.h, json={'customer_ids': [customer]}).json()['created'][0]
    route = client.post('/api/routes', headers=biz.h, json={
        'name': 'Delete lifecycle route', 'default_staff_id': staff['id'], 'shop_ids': [shop['id']],
    }).json()
    run = _plan(client, biz, staff['id'], [{'shop_id': shop['id'], 'invoice_ids': [invoice], 'collect_due': True}], route_id=route['id'])
    stop = run['stops'][0]
    check_in(client, headers)
    assert client.post(f"/api/run-stops/{stop['id']}/arrive", headers=headers, json={'geo': geo()}).status_code == 200
    delivery = next(task for task in stop['tasks'] if task['task_type'] == 'delivery')
    assert client.post(f"/api/tasks/{delivery['id']}/complete", headers=headers,
                       json={'geo': geo(), 'boxes_delivered': 1}).status_code == 200
    assert client.post('/api/requests', headers=headers, json={
        'shop_id': shop['id'], 'run_stop_id': stop['id'], 'kind': 'order',
        'items': [{'name': 'Fixture request', 'qty': 1, 'unit': 'Box'}], 'geo': geo(),
    }).status_code == 201
    other = Biz(client)
    other.staff()
    other.shop('Surviving fixture')
    admin = billing_admin(monkeypatch)
    with SessionLocal() as db:
        owned = counts(db, biz.business_id)
        assert len(owned) == 14 and all(count > 0 for count in owned.values()), owned
        survivor = counts(db, other.business_id)
        admin.wipe_user_data(biz.business_id, db)
        assert all(count == 0 for count in counts(db, biz.business_id).values())
        assert counts(db, other.business_id) == survivor
        assert db.get(BillingUser, other.business_id) is not None
    assert client.get('/api/auth/me', headers=biz.h).status_code == 401
    assert client.get('/api/auth/me', headers=headers).status_code == 401
    assert client.get('/api/auth/me', headers=other.h).status_code == 200


def test_foreign_field_reference_blocks_wipe_before_deleting_any_business(client, biz, monkeypatch):
    staff = biz.staff()
    other = Biz(client)
    with SessionLocal() as db:
        db.add(FieldTask(business_id=other.business_id, staff_id=staff['id'],
                         title='Malformed foreign fixture', task_type='general'))
        db.commit()
        before_target, before_other = counts(db, biz.business_id), counts(db, other.business_id)
        admin = billing_admin(monkeypatch)
        with pytest.raises(HTTPException) as error:
            admin.wipe_user_data(biz.business_id, db)
        assert error.value.status_code == 409
        assert 'another business has a Field reference' in error.value.detail
        assert counts(db, biz.business_id) == before_target
        assert counts(db, other.business_id) == before_other
        assert db.get(BillingUser, biz.business_id) is not None
        db.rollback()
