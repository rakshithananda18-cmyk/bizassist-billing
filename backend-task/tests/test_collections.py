"""Field collections: how staff record a payment, and what the owner has
confirmed in billing (app/collections.py). Billing's confirm itself is tested
in billing (backend/tests/test_field_collections.py); here its payment rows are
written the way billing writes them."""
from app.billing_models import BillingCustomer, BillingInvoice, BillingInvoicePayment
from app.db import SessionLocal
from app.models import FieldTask
from tests.conftest import check_in, geo


def _collect_task(client, biz, staff_id, shop_id, expected=500.0):
    r = client.post("/api/tasks", headers=biz.h, json={
        "title": "Collect dues", "task_type": "payment_collect", "staff_id": staff_id,
        "shop_id": shop_id, "amount_expected": expected, "due_time": "23:59"})
    assert r.status_code == 201, r.text
    return r.json()


def _complete(client, h, task_id, **body):
    return client.post(f"/api/tasks/{task_id}/complete", headers=h, json={"geo": geo(), **body})


def _done(client, biz):
    return {t["id"]: t for t in client.get("/api/tasks", headers=biz.h, params={"status": "done"}).json()}


def test_staff_record_how_they_were_paid(client, biz):
    s, h = biz.staff_session()
    shop = biz.shop()
    check_in(client, h)
    upi = _collect_task(client, biz, s["id"], shop["id"])
    r = _complete(client, h, upi["id"], amount_collected=500, payment_mode="UPI", payment_ref=" 4512-7781 ")
    assert r.status_code == 200, r.text
    assert (r.json()["payment_mode"], r.json()["payment_ref"]) == ("UPI", "4512-7781")

    cash = _collect_task(client, biz, s["id"], shop["id"])
    assert _complete(client, h, cash["id"], amount_collected=300).json()["payment_mode"] == "Cash"  # older app: no mode sent
    nothing = _collect_task(client, biz, s["id"], shop["id"])
    assert _complete(client, h, nothing["id"], amount_collected=0, payment_mode="UPI").json()["payment_mode"] is None

    bad = _collect_task(client, biz, s["id"], shop["id"])
    assert _complete(client, h, bad["id"], amount_collected=10, payment_mode="Bitcoin").status_code == 422


def test_owner_sees_what_billing_has_recorded(client, biz, other_biz):
    s, h = biz.staff_session()
    shop = biz.shop()
    check_in(client, h)
    t = _collect_task(client, biz, s["id"], shop["id"])
    _complete(client, h, t["id"], amount_collected=500, payment_mode="Cash")
    assert _done(client, biz)[t["id"]]["billing_confirmed"] == 0.0

    db = SessionLocal()
    try:
        uid = db.query(FieldTask.uid).filter(FieldTask.id == t["id"]).scalar()
        c = BillingCustomer(business_id=biz.business_id, name="Payer")
        db.add(c)
        db.flush()
        a = BillingInvoice(business_id=biz.business_id, customer_id=c.id, invoice_id="INV-1", total_amount=400, paid_amount=0)
        b = BillingInvoice(business_id=biz.business_id, customer_id=c.id, invoice_id="INV-2", total_amount=400, paid_amount=0)
        db.add_all([a, b])
        db.flush()
        # As billing's confirm writes them: one payment per bill, keyed by task and bill.
        db.add_all([
            BillingInvoicePayment(business_id=biz.business_id, invoice_id=a.id, amount_paid=400, idempotency_key=f"ft-collect:{uid}:{a.id}"),
            BillingInvoicePayment(business_id=biz.business_id, invoice_id=b.id, amount_paid=50, idempotency_key=f"ft-collect:{uid}:{b.id}"),
            BillingInvoicePayment(business_id=biz.business_id, invoice_id=b.id, amount_paid=25,
                                  idempotency_key=f"ft-collect:{uid}:{b.id}:after:45000"),  # continued confirmation
            BillingInvoicePayment(business_id=biz.business_id, invoice_id=b.id, amount_paid=999, idempotency_key="pos-123"),  # not ours
            BillingInvoicePayment(business_id=other_biz.business_id, invoice_id=b.id, amount_paid=77,
                                  idempotency_key=f"ft-collect:{uid}:{b.id}x"),  # another business
        ])
        db.commit()
    finally:
        db.close()
    assert _done(client, biz)[t["id"]]["billing_confirmed"] == 475.0
