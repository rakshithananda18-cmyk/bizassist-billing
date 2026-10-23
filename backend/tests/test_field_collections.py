"""
Field Team collections confirmed into the books (core/field_team.py).

Field Team's tables are created here from billing's read-only declarations (in
production Field Team's own migrations create them in the shared cloud
database); rows are inserted the way Field Team writes them.
"""
import os
import sys
import uuid
from datetime import datetime

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, backend_path)

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from main_groq import app
from core import field_team
from core.field_team import FieldTeamBase, FtShop, FtStaff, FtTask, FtTaskInvoice
from database.db import SessionLocal, engine
from database.models import Customer, Invoice, InvoicePayment, Product

client = TestClient(app)


@pytest.fixture(scope="module", autouse=True)
def field_team_tables():
    FieldTeamBase.metadata.create_all(bind=engine)
    yield
    FieldTeamBase.metadata.drop_all(bind=engine)


def _signup(role=None):
    username = f"fc_owner_{uuid.uuid4().hex[:8]}"
    body = client.post("/signup", json={"username": username, "password": "TestPass123!",
                                        "business_name": "Field Biz"}).json()
    headers = {"Authorization": f"Bearer {body['token']}"}
    if role:
        from services.auth import create_access_token
        headers = {"Authorization": "Bearer " + create_access_token(
            {"id": body["id"], "username": username, "business_name": "Field Biz", "role": role})}
    return body["id"], headers


@pytest.fixture
def owner():
    return _signup()


def _bill(headers, cid, pid, qty, invoice_date):
    """A real sale through billing (₹118 per unit: 100 + 18% GST), back-dated."""
    r = client.post("/sales", headers=headers, json={
        "place_of_supply": "29", "customer_id": cid, "paid_amount": 0.0,
        "lines": [{"product_id": pid, "quantity": qty, "unit_price": 100}]})
    assert r.status_code == 200, r.text
    db = SessionLocal()
    try:
        inv = db.query(Invoice).filter(Invoice.id == r.json()["id"]).first()
        inv.invoice_date = invoice_date
        db.commit()
        return inv.id, inv.invoice_id, inv.total_amount
    finally:
        db.close()


def _field_setup(bid, headers, *, amount, link_bills=True, mode="UPI", ref="UPI-778812"):
    db = SessionLocal()
    try:
        c = Customer(business_id=bid, name="Sri Balaji Medicals")
        p = Product(business_id=bid, name="Paracetamol", selling_price=100, track_inventory=False,
                    cgst_rate=9.0, sgst_rate=9.0)
        db.add_all([c, p])
        db.commit()
        cid, pid = c.id, p.id
    finally:
        db.close()
    newer = _bill(headers, cid, pid, 2, "2026-10-20")   # ₹236
    older = _bill(headers, cid, pid, 10, "2026-10-01")  # ₹1180
    db = SessionLocal()
    try:
        shop = FtShop(business_id=bid, name="Sri Balaji Medicals", customer_id=cid)
        staff = FtStaff(business_id=bid, name="Kiran")
        db.add_all([shop, staff])
        db.flush()
        task = FtTask(uid=str(uuid.uuid4()), business_id=bid, task_type="payment_collect",
                      title="Collect dues", staff_id=staff.id, shop_id=shop.id, status="done",
                      amount_collected=amount, payment_mode=mode, payment_ref=ref,
                      completed_at=datetime(2026, 10, 23, 19, 0))  # 00:30 IST on the 24th
        db.add(task)
        db.flush()
        if link_bills:
            db.add_all([FtTaskInvoice(business_id=bid, task_id=task.id, invoice_id=newer[0]),
                        FtTaskInvoice(business_id=bid, task_id=task.id, invoice_id=older[0])])
        db.commit()
        return {"task_uid": task.uid, "older": older, "newer": newer, "customer_id": cid}
    finally:
        db.close()


def _payments(bid):
    db = SessionLocal()
    try:
        return db.query(InvoicePayment).filter(InvoicePayment.business_id == bid,
                                               InvoicePayment.idempotency_key.like("ft-collect:%")).all()
    finally:
        db.close()


def test_owner_confirms_a_collection_oldest_bill_first(owner):
    bid, h = owner
    s = _field_setup(bid, h, amount=1300.0)
    listed = client.get("/field-collections", headers=h).json()
    assert listed["available"] is True
    [c] = listed["collections"]
    assert (c["shop"], c["staff"], c["payment_mode"], c["payment_ref"]) == ("Sri Balaji Medicals", "Kiran", "UPI", "UPI-778812")
    assert c["remaining"] == 1300.0 and c["collected_on"] == "2026-10-24"
    assert [b["number"] for b in c["bills"]] == [s["older"][1], s["newer"][1]]  # oldest first
    assert c["suggested"] == [{"invoice_id": s["older"][0], "amount": 1180.0},
                              {"invoice_id": s["newer"][0], "amount": 120.0}]
    assert c["unallocated"] == 0.0

    r = client.post(f"/field-collections/{c['task_uid']}/confirm", headers=h, json={"allocations": c["suggested"]})
    assert r.status_code == 200, r.text
    assert r.json()["confirmed_total"] == 1300.0 and r.json()["remaining"] == 0.0

    pays = {p.invoice_id: p for p in _payments(bid)}
    assert pays[s["older"][0]].amount_paid == 1180.0 and pays[s["newer"][0]].amount_paid == 120.0
    assert all(p.payment_mode == "UPI" and p.payment_date == "2026-10-24" for p in pays.values())
    assert pays[s["older"][0]].idempotency_key == f"ft-collect:{s['task_uid']}:{s['older'][0]}"
    assert "Kiran" in pays[s["older"][0]].note and "UPI-778812" in pays[s["older"][0]].note
    db = SessionLocal()
    try:
        status = {i.id: (i.status, i.paid_amount) for i in db.query(Invoice).filter(Invoice.business_id == bid)}
    finally:
        db.close()
    assert status[s["older"][0]] == ("Paid", 1180.0) and status[s["newer"][0]] == ("Partial", 120.0)
    assert client.get("/field-collections", headers=h).json()["collections"] == []


def test_confirming_twice_never_records_twice(owner):
    bid, h = owner
    s = _field_setup(bid, h, amount=500.0)
    plan = [{"invoice_id": s["older"][0], "amount": 500.0}]
    assert client.post(f"/field-collections/{s['task_uid']}/confirm", headers=h, json={"allocations": plan}).status_code == 200
    again = client.post(f"/field-collections/{s['task_uid']}/confirm", headers=h, json={"allocations": plan})
    assert again.status_code == 422 and "already recorded" in again.json()["detail"]
    assert len(_payments(bid)) == 1


def test_part_now_rest_later(owner):
    bid, h = owner
    s = _field_setup(bid, h, amount=400.0)
    r = client.post(f"/field-collections/{s['task_uid']}/confirm", headers=h,
                    json={"allocations": [{"invoice_id": s["newer"][0], "amount": 236.0}]})
    assert r.json()["remaining"] == 164.0
    [c] = client.get("/field-collections", headers=h).json()["collections"]
    assert c["already_confirmed"] == 236.0 and c["remaining"] == 164.0
    assert [b["invoice_id"] for b in c["bills"]] == [s["older"][0]]  # the paid bill is not offered again


@pytest.mark.parametrize("plan, detail", [
    (lambda s: [{"invoice_id": s["newer"][0], "amount": 300.0}], "is due"),          # more than the bill
    (lambda s: [{"invoice_id": s["older"][0], "amount": 1180.0}], "left to confirm"),  # more than collected
    (lambda s: [{"invoice_id": 999999, "amount": 10.0}], "cannot take"),
    (lambda s: [{"invoice_id": s["older"][0], "amount": 0}], "at least one"),
])
def test_splits_that_do_not_fit_are_refused(owner, plan, detail):
    bid, h = owner
    s = _field_setup(bid, h, amount=1000.0)
    r = client.post(f"/field-collections/{s['task_uid']}/confirm", headers=h, json={"allocations": plan(s)})
    assert r.status_code == 422 and detail in r.json()["detail"]
    assert _payments(bid) == []


def test_collection_without_bills_uses_the_customers_unpaid_bills(owner):
    bid, h = owner
    s = _field_setup(bid, h, amount=1416.0, link_bills=False, mode=None, ref=None)
    [c] = client.get("/field-collections", headers=h).json()["collections"]
    assert c["payment_mode"] == "Cash"
    assert c["suggested"] == [{"invoice_id": s["older"][0], "amount": 1180.0},
                              {"invoice_id": s["newer"][0], "amount": 236.0}]


def test_more_collected_than_due_shows_what_is_left(owner):
    bid, h = owner
    _field_setup(bid, h, amount=2000.0)
    [c] = client.get("/field-collections", headers=h).json()["collections"]
    assert c["unallocated"] == 584.0  # 2000 − (1180 + 236): recorded by hand, not guessed


def test_owner_only_and_own_business_only(owner):
    bid, h = owner
    s = _field_setup(bid, h, amount=100.0)
    _, cashier = _signup(role="cashier")
    assert client.get("/field-collections", headers=cashier).status_code == 403
    _, other = _signup()
    assert client.get("/field-collections", headers=other).json()["collections"] == []
    r = client.post(f"/field-collections/{s['task_uid']}/confirm", headers=other,
                    json={"allocations": [{"invoice_id": s["older"][0], "amount": 100.0}]})
    assert r.status_code == 404
    assert _payments(bid) == []


def test_unavailable_where_field_team_tables_do_not_exist():
    with Session(bind=create_engine("sqlite://")) as db:  # the desktop app's database
        assert field_team.available(db) is False
