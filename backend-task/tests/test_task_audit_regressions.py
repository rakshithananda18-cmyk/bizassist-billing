"""Task edit validation, run alignment and concurrent completion safety."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import json

import pytest
from sqlalchemy import event

from app.db import SessionLocal, engine
from app.models import FieldAttendance, FieldPointsEntry, FieldTask
from app.timeutil import biz_local_to_utc, biz_today
from tests.conftest import check_in, geo
from tests.test_runs_tasks import _plan
from tests.test_billing_invoices import linked


def task(client, biz, staff_id, **extra):
    response = client.post('/api/tasks', headers=biz.h,
        json={'title': 'Audit fixture task', 'staff_id': staff_id, **extra})
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.parametrize('patch', [{'staff_id': None}, {'title': None}, {'points': None},
                                   {'status': None}, {'title': '   '}])
def test_invalid_task_patch_is_a_validation_error_not_server_failure(client, biz, patch):
    staff = biz.staff()
    original = task(client, biz, staff['id'])
    response = client.patch(f"/api/tasks/{original['id']}", headers=biz.h, json=patch)
    assert response.status_code == 422, response.text
    with SessionLocal() as db:
        saved = db.get(FieldTask, original['id'])
        assert (saved.title, saved.staff_id, saved.status) == ('Audit fixture task', staff['id'], 'pending')


def test_updating_only_due_time_preserves_business_date(client, biz):
    staff = biz.staff()
    original = task(client, biz, staff['id'], due_date=biz_today(), due_time='18:00')
    response = client.patch(f"/api/tasks/{original['id']}", headers=biz.h, json={'due_time': '16:30'})
    assert response.status_code == 200, response.text
    with SessionLocal() as db:
        assert db.get(FieldTask, original['id']).due_at == biz_local_to_utc(biz_today(), '16:30')
    response = client.patch(f"/api/tasks/{original['id']}", headers=biz.h, json={'due_date': None})
    assert response.status_code == 200, response.text
    assert response.json()['due_at'] is None


def test_due_time_without_a_date_is_refused(client, biz):
    staff = biz.staff()
    original = task(client, biz, staff['id'])
    response = client.patch(f"/api/tasks/{original['id']}", headers=biz.h, json={'due_time': '16:30'})
    assert response.status_code == 422, response.text


def test_route_task_cannot_move_independently_of_the_run(client, biz):
    first, second = biz.staff(name='First'), biz.staff(name='Second')
    shop = biz.shop()
    run = _plan(client, biz, first['id'], [{'shop_id': shop['id'], 'boxes': 1}])
    child = run['stops'][0]['tasks'][0]
    response = client.patch(f"/api/tasks/{child['id']}", headers=biz.h, json={'staff_id': second['id']})
    assert response.status_code == 409, response.text
    saved = client.get(f"/api/runs/{run['id']}", headers=biz.h).json()
    assert saved['staff_id'] == first['id']
    assert saved['stops'][0]['tasks'][0]['staff_id'] == first['id']
    response = client.patch(f"/api/runs/{run['id']}", headers=biz.h, json={'staff_id': second['id']})
    assert response.status_code == 200, response.text
    assert response.json()['stops'][0]['tasks'][0]['staff_id'] == second['id']


@pytest.mark.parametrize('number', ['1e309', 'NaN', 'Infinity', '"Infinity"'])
def test_nonfinite_collection_amounts_cannot_complete_or_change_a_task(client, biz, number):
    staff, headers = biz.staff_session()
    check_in(client, headers)
    original = task(client, biz, staff['id'], task_type='payment_collect', amount_expected=30)
    body = '{"geo":' + json.dumps(geo()) + ',"amount_collected":' + number + '}'
    response = client.post(f"/api/tasks/{original['id']}/complete", headers={**headers, 'Content-Type': 'application/json'}, content=body)
    assert response.status_code == 422, response.text
    assert response.json()['detail'][0]['loc'][-1] == 'amount_collected'
    with SessionLocal() as db:
        saved = db.get(FieldTask, original['id'])
        assert saved.status == 'pending' and saved.amount_collected is None
        assert db.query(FieldPointsEntry).filter_by(task_id=original['id']).count() == 0


def test_nonfinite_expected_amounts_are_refused_in_task_and_route_plans(client, biz):
    staff = biz.staff()
    headers = {**biz.h, 'Content-Type': 'application/json'}
    body = json.dumps({'title': 'Invalid amount fixture', 'staff_id': staff['id']})[:-1] + ',"amount_expected":1e309}'
    assert client.post('/api/tasks', headers=headers, content=body).status_code == 422
    original = task(client, biz, staff['id'])
    assert client.patch(f"/api/tasks/{original['id']}", headers=headers,
                        content='{"amount_expected":1e309}').status_code == 422
    shop = biz.shop()
    plan = {'run_date': biz_today(), 'staff_id': staff['id'], 'stops': [{
        'shop_id': shop['id'], 'tasks': [{'task_type': 'payment_collect', 'title': 'Invalid route amount', 'amount_expected': 'Infinity'}],
    }]}
    assert client.post('/api/runs', headers=biz.h, json=plan).status_code == 422


@pytest.mark.parametrize('field', ['lat', 'lng', 'accuracy', 'speed', 'heading'])
def test_nonfinite_gps_evidence_is_rejected_without_creating_attendance(client, biz, field):
    staff, headers = biz.staff_session()
    fix = geo()
    fix.pop(field, None)
    raw_geo = json.dumps(fix)[:-1] + ',"' + field + '":1e309}'
    response = client.post('/api/attendance/check-in', headers={**headers, 'Content-Type': 'application/json'},
                           content='{"geo":' + raw_geo + '}')
    assert response.status_code == 422, response.text
    with SessionLocal() as db:
        assert db.query(FieldAttendance).filter_by(staff_id=staff['id']).count() == 0


def test_two_inflight_completions_award_points_only_once(client, biz):
    if engine.dialect.name != 'postgresql':
        pytest.skip('Requires real PostgreSQL row-lock semantics')
    staff, headers = biz.staff_session()
    check_in(client, headers)
    original = task(client, biz, staff['id'], task_type='payment_collect', amount_expected=30, points=10)
    gate = Barrier(2)

    def align_requests(conn, cursor, statement, params, context, executemany):
        if statement.lstrip().upper().startswith('SELECT') and 'FOR UPDATE OF ft_tasks' in statement:
            gate.wait(timeout=15)

    event.listen(engine, 'before_cursor_execute', align_requests)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(lambda amount: client.post(
                f"/api/tasks/{original['id']}/complete", headers=headers,
                json={'geo': geo(), 'amount_collected': amount}), [20, 30]))
    finally:
        event.remove(engine, 'before_cursor_execute', align_requests)
    assert sorted(response.status_code for response in responses) == [200, 409]
    with SessionLocal() as db:
        assert db.query(FieldPointsEntry).filter_by(task_id=original['id']).count() == 1
        saved = db.get(FieldTask, original['id'])
        assert saved.status == 'done' and saved.amount_collected in (20, 30)


def test_two_planners_cannot_assign_the_same_bill_twice(client, biz, linked):
    if engine.dialect.name != 'postgresql':
        pytest.skip('Requires real PostgreSQL row-lock semantics')
    shop, _customer, bills = linked
    staff = biz.staff()
    gate = Barrier(2)

    def align_requests(conn, cursor, statement, params, context, executemany):
        if statement.lstrip().upper().startswith('SELECT') and 'FOR UPDATE OF invoices' in statement:
            gate.wait(timeout=15)

    def plan(_):
        return client.post('/api/tasks', headers=biz.h, json={
            'title': 'Concurrent billing delivery', 'staff_id': staff['id'], 'shop_id': shop['id'],
            'task_type': 'delivery', 'invoice_ids': [bills['boxes']],
        })

    event.listen(engine, 'before_cursor_execute', align_requests)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(plan, range(2)))
    finally:
        event.remove(engine, 'before_cursor_execute', align_requests)
    assert sorted(response.status_code for response in responses) == [201, 409]
