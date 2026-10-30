"""Read-only-to-workspace audit proof; all data is synthetic in memory.

Execute from repo root with a Python environment containing backend-task deps.
Calls the actual command handlers directly; does not establish an HTTP/RLS pass.
"""
from pathlib import Path
import json
import os
import socket
import sys

ROOT = Path(__file__).resolve().parents[3]
os.environ.update({
    'DATABASE_URL': 'sqlite:///:memory:',
    'JWT_SECRET': 'test-only-secret-please-change-0123456789abcdef',
    'TASK_CREATE_BILLING_MIRROR': '1', 'TASK_PURGE_LOOP': '0',
    'SUBSCRIPTION_ENFORCED': '0', 'SPACE_ID': '', 'K_SERVICE': '',
    'ENVIRONMENT': '', 'LOG_LEVEL': 'ERROR', 'TASK_CRON_SECRET': '',
})
def deny_network(*args, **kwargs):
    raise OSError('Network disabled in isolated audit reproduction')
socket.socket.connect = deny_network
socket.getaddrinfo = deny_network
sys.path.insert(0, str(ROOT / 'backend-task'))
import dotenv
dotenv.load_dotenv = lambda *_a, **_kw: False
print('Loading isolated Field handlers...', flush=True)
from app.main import prepare_database
from app.billing_models import BillingUser, BillingCustomer, BillingInvoice
from app.db import SessionLocal, utc_now
from app.models import FieldStaff, FieldShop, FieldAttendance
from app.security import Principal
from app.geo import GeoFix
from app.routers.tasks import create_task, update_task, complete_task, TaskIn, TaskPatch, CompleteBody
from app.timeutil import biz_today

prepare_database()
with SessionLocal() as db:
    owner = BillingUser(username='audit_fixture', password='unused', role='enterprise', public_id='BA-AUDIT1')
    db.add(owner)
    db.flush()
    staff = FieldStaff(business_id=owner.id, name='Audit courier', login_name='audit', password_hash='unused', role='delivery')
    customer = BillingCustomer(business_id=owner.id, name='Synthetic customer')
    db.add_all([staff, customer])
    db.flush()
    shop = FieldShop(business_id=owner.id, name='Synthetic shop', customer_id=customer.id, lat=12.97, lng=77.59)
    invoice = BillingInvoice(business_id=owner.id, customer_id=customer.id, invoice_id='AUDIT-100',
                             amount=100, total_amount=100, paid_amount=0, status='Pending', invoice_type='B2B')
    db.add_all([shop, invoice])
    db.flush()
    att = FieldAttendance(business_id=owner.id, staff_id=staff.id, work_date=biz_today(),
                          check_in_at=utc_now(), check_in_lat=12.97, check_in_lng=77.59)
    db.add(att)
    db.commit()
    op = Principal(kind='owner', business_id=owner.id, owner_user_id=owner.id, owner=owner)
    sp = Principal(kind='staff', business_id=owner.id, staff=staff, owner=owner)
    payload = dict(title='Collect synthetic invoice', task_type='payment_collect', staff_id=staff.id,
                   shop_id=shop.id, invoice_ids=[invoice.id])
    first = create_task(TaskIn(**payload), p=op, db=db)
    update_task(first['id'], TaskPatch(status='cancelled'), p=op, db=db)
    replacement = create_task(TaskIn(**payload), p=op, db=db)
    reopened = update_task(first['id'], TaskPatch(status='pending'), p=op, db=db)
    assert reopened['status'] == 'pending'
    body = CompleteBody(geo=GeoFix(lat=12.97, lng=77.59, accuracy=5), amount_collected=100)
    a = complete_task(first['id'], body, p=sp, db=db)
    b = complete_task(replacement['id'], body, p=sp, db=db)
    result = {
        'finding': 'FT-01', 'cancelled_task_reopened_despite_replacement': reopened['status'],
        'completion_statuses': [a['status'], b['status']],
        'invoice_due': 100, 'reported_collected': a['amount_collected'] + b['amount_collected'],
        'scope': 'actual handlers; synthetic in-memory SQLite; no HTTP, network or live DB',
    }
    assert result['reported_collected'] == 200
    print(json.dumps(result, indent=2), flush=True)
