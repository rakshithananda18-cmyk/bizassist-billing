"""Current billing data follows a business into field work, without changing
the historical planning snapshots or writing payments from Field Team."""
import pytest
from sqlalchemy import event

from app.billing_models import BillingCustomer, BillingInvoice, BillingInvoicePayment, BillingUser
from app import config
from app.db import SessionLocal, engine
from app.models import FieldShop, FieldTask
from app.security import _encode
from app.timeutil import biz_today
from tests.conftest import auth, check_in, geo
from tests.test_billing_invoices import _bill, _customer


def linked_task(client, biz, *, task_type="payment_collect", total=1000, expected=None):
    cid = _customer(biz.business_id, "Original Medicals")
    shop = client.post("/api/shops/import-billing", headers=biz.h,
                       json={"customer_ids": [cid]}).json()["created"][0]
    invoice_id = _bill(biz.business_id, cid, "INV-LIVE", total=total)
    staff, staff_headers = biz.staff_session()
    body = {"title": "Collect billing dues", "task_type": task_type, "staff_id": staff["id"],
            "shop_id": shop["id"], "invoice_ids": [invoice_id]}
    if expected is not None:
        body["amount_expected"] = expected
    created = client.post("/api/tasks", headers=biz.h, json=body)
    assert created.status_code == 201, created.text
    return cid, shop, invoice_id, staff, staff_headers, created.json()


def test_business_identity_follows_billing_profile_edits(client, biz):
    db = SessionLocal()
    try:
        owner = db.get(BillingUser, biz.business_id)
        owner.business_name, owner.phone = "Updated Billing Business", "9876543210"
        db.commit()
    finally:
        db.close()
    body = client.get("/api/auth/me", headers=biz.h).json()
    assert body["business_name"] == "Updated Billing Business"
    assert body["billing_business"] == {"business_id": biz.business_id, "public_id": biz.public_id,
                                        "business_name": "Updated Billing Business", "phone": "9876543210"}
    assert body["data_source"] == {"mode": "local" if config.IS_SQLITE else "cloud", "shared_database_required": True,
                                    "cloud_only": True, "development_mirror": config.IS_SQLITE}
    assert "DATABASE_URL" not in str(body) and "JWT_SECRET" not in str(body)


def test_linked_customer_identity_is_live_but_field_details_stay_local(client, biz):
    cid, shop, _, staff, staff_headers, task = linked_task(client, biz)
    assert client.patch(f"/api/shops/{shop['id']}", headers=biz.h,
                        json={"contact_name": "Shop manager", "notes": "Use side entrance", "lat": 12.97, "lng": 77.59}).status_code == 200
    db = SessionLocal()
    try:
        customer = db.get(BillingCustomer, cid)
        customer.name, customer.phone, customer.address = "Renamed in Billing", "9990001111", "New billing address"
        db.commit()
    finally:
        db.close()
    row = next(s for s in client.get("/api/shops", headers=biz.h).json() if s["id"] == shop["id"])
    assert (row["name"], row["phone"], row["address"]) == ("Renamed in Billing", "9990001111", "New billing address")
    assert row["billing_customer"]["id"] == cid and row["billing_customer_available"] is True
    assert row["notes"] == "Use side entrance" and row["contact_name"] == "Shop manager" and row["lat"] == 12.97
    assert client.get(f"/api/tasks/{task['id']}", headers=staff_headers).json()["shop_name"] == "Renamed in Billing"
    # Reading did not mutate either Billing or the imported Field snapshot.
    db = SessionLocal()
    try:
        assert db.get(FieldShop, shop["id"]).name == "Original Medicals"
        assert db.get(BillingCustomer, cid).name == "Renamed in Billing"
    finally:
        db.close()


def test_linked_shared_fields_cannot_diverge_but_equal_form_submission_works(client, biz):
    cid, shop, *_ = linked_task(client, biz)
    same = client.patch(f"/api/shops/{shop['id']}", headers=biz.h,
                        json={"name": shop["name"], "phone": shop["phone"], "address": shop["address"], "area": "South"})
    assert same.status_code == 200 and same.json()["area"] == "South"
    changed = client.patch(f"/api/shops/{shop['id']}", headers=biz.h, json={"phone": "1234567890"})
    assert changed.status_code == 422
    assert "managed in BizAssist Billing" in changed.json()["detail"]


def test_current_balance_changes_without_rewriting_planned_snapshot(client, biz):
    _, _, invoice_id, _, staff_headers, task = linked_task(client, biz, expected=500)
    db = SessionLocal()
    try:
        invoice = db.get(BillingInvoice, invoice_id)
        invoice.paid_amount, invoice.status = 700, "Partial"
        db.commit()
    finally:
        db.close()
    for rows in (client.get("/api/my/tasks", headers=staff_headers).json(),
                 client.get("/api/tasks", headers=biz.h).json(),
                 client.get("/api/my/today", headers=staff_headers).json()["other_tasks"]):
        live = next(row for row in rows if row["id"] == task["id"])
        assert live["amount_expected"] == 500 and live["invoices"][0]["balance_due"] == 1000
        assert live["current_amount_due"] == 300 and live["billing_balance_available"] is True
        assert live["invoices"][0]["current_paid"] == 700
        assert live["invoices"][0]["current_status"] == "Partial"


def test_completion_rechecks_current_billing_due_and_never_posts_a_payment(client, biz):
    _, _, invoice_id, _, staff_headers, task = linked_task(client, biz)
    check_in(client, staff_headers)
    db = SessionLocal()
    try:
        db.get(BillingInvoice, invoice_id).paid_amount = 800
        db.commit()
    finally:
        db.close()

    stale = client.post(f"/api/tasks/{task['id']}/complete", headers=staff_headers,
                        json={"geo": geo(), "amount_collected": 1000})
    assert stale.status_code == 409 and "balance has changed" in stale.json()["detail"]
    done = client.post(f"/api/tasks/{task['id']}/complete", headers=staff_headers,
                       json={"geo": geo(), "amount_collected": 200})
    assert done.status_code == 200 and done.json()["amount_collected"] == 200
    db = SessionLocal()
    try:
        assert db.get(BillingInvoice, invoice_id).paid_amount == 800
        assert db.query(BillingInvoicePayment).filter(BillingInvoicePayment.business_id == biz.business_id).count() == 0
    finally:
        db.close()


def test_unconfirmed_collected_cash_keeps_the_original_shop_customer(client, biz):
    customer_id, shop, _, _, staff_headers, task = linked_task(client, biz)
    check_in(client, staff_headers)
    complete = client.post(f"/api/tasks/{task['id']}/complete", headers=staff_headers,
                           json={"geo": geo(), "amount_collected": 10})
    assert complete.status_code == 200
    relink = client.patch(f"/api/shops/{shop['id']}", headers=biz.h, json={"customer_id": None})
    assert relink.status_code == 409 and "collected money" in relink.json()['detail']
    [current] = client.get('/api/shops', headers=biz.h).json()
    assert current['customer_id'] == customer_id


@pytest.mark.parametrize("change", ["missing", "different_customer", "different_tenant", "credit_note", "cancelled"])
def test_unavailable_linked_invoices_never_fall_back_to_old_amounts(client, biz, other_biz, change):
    _, _, invoice_id, _, staff_headers, task = linked_task(client, biz)
    db = SessionLocal()
    try:
        invoice = db.get(BillingInvoice, invoice_id)
        if change == "missing":
            db.delete(invoice)
        elif change == "different_customer":
            customer = BillingCustomer(business_id=biz.business_id, name="Other customer")
            db.add(customer)
            db.flush()
            invoice.customer_id = customer.id
        elif change == "different_tenant":
            foreign_customer = BillingCustomer(business_id=other_biz.business_id, name="Private customer")
            db.add(foreign_customer)
            db.flush()
            foreign_invoice = BillingInvoice(business_id=other_biz.business_id, customer_id=foreign_customer.id,
                                             invoice_id="PRIVATE", total_amount=987654, paid_amount=500)
            db.add(foreign_invoice)
            db.flush()
            db.get(FieldTask, task["id"]).invoices[0].invoice_id = foreign_invoice.id
        elif change == "cancelled":
            invoice.status = "Cancelled"
        else:
            invoice.invoice_type = "credit_note"
        db.commit()
    finally:
        db.close()
    body = client.get(f"/api/tasks/{task['id']}", headers=staff_headers).json()
    assert body["billing_balance_available"] is False and body["current_amount_due"] is None
    assert body["invoices"][0]["available"] is False
    assert body["invoices"][0]["current_balance_due"] is None
    check_in(client, staff_headers)
    assert client.post(f"/api/tasks/{task['id']}/complete", headers=staff_headers,
                       json={"geo": geo(), "amount_collected": 1}).status_code == 409


def test_task_detail_obeys_both_business_and_staff_assignment(client, biz, other_biz):
    _, _, _, _, staff_headers, task = linked_task(client, biz)
    _, second_staff = biz.staff_session("Someone else")
    assert client.get(f"/api/tasks/{task['id']}", headers=staff_headers).status_code == 200
    assert client.get(f"/api/tasks/{task['id']}", headers=biz.h).status_code == 200
    assert client.get(f"/api/tasks/{task['id']}", headers=second_staff).status_code == 404
    assert client.get(f"/api/tasks/{task['id']}", headers=other_biz.h).status_code == 404


def test_shop_cannot_be_relinked_away_from_pending_invoice_tasks(client, biz):
    cid, shop, _, _, _, task = linked_task(client, biz)
    other = _customer(biz.business_id, "New destination")
    for new_link in (None, other):
        refused = client.patch(f"/api/shops/{shop['id']}", headers=biz.h, json={"customer_id": new_link})
        assert refused.status_code == 409 and "pending invoice tasks" in refused.json()["detail"]
    assert client.patch(f"/api/tasks/{task['id']}", headers=biz.h, json={"status": "cancelled"}).status_code == 200
    assert client.patch(f"/api/shops/{shop['id']}", headers=biz.h, json={"customer_id": other}).status_code == 200


def test_confirmed_partial_collection_can_be_planned_again(client, biz):
    _, shop, invoice_id, staff, staff_headers, task = linked_task(client, biz)
    check_in(client, staff_headers)
    assert client.post(f"/api/tasks/{task['id']}/complete", headers=staff_headers,
                       json={"geo": geo(), "amount_collected": 200}).status_code == 200
    body = {"title": "Remaining balance", "task_type": "payment_collect", "staff_id": staff["id"],
            "shop_id": shop["id"], "invoice_ids": [invoice_id]}
    assert client.post("/api/tasks", headers=biz.h, json=body).status_code == 409  # cash not yet confirmed
    db = SessionLocal()
    try:
        uid = db.get(FieldTask, task["id"]).uid
        db.add(BillingInvoicePayment(business_id=biz.business_id, invoice_id=invoice_id,
                                    amount_paid=200, idempotency_key=f"ft-collect:{uid}:{invoice_id}"))
        db.get(BillingInvoice, invoice_id).paid_amount = 200
        db.commit()
    finally:
        db.close()
    repeated = client.post("/api/tasks", headers=biz.h, json=body)
    assert repeated.status_code == 201, repeated.text
    assert repeated.json()["amount_expected"] == 800


@pytest.mark.parametrize("kind", ["owner", "staff"])
def test_task_sessions_do_not_cross_an_id_colliding_business_database(client, biz, kind):
    if kind == "owner":
        token = _encode({"typ": "owner", "bid": biz.business_id, "uid": biz.business_id,
                         "public_id": "BA-OTHER1", "tv": 0})
    else:
        staff = biz.staff()
        biz.login_staff(staff["login_name"])
        from app.models import FieldStaff
        db = SessionLocal()
        try:
            row = db.get(FieldStaff, staff["id"])
            token = _encode({"typ": "staff", "bid": biz.business_id, "sid": row.id,
                             "ses": row.active_session_id, "dev": row.active_device_id,
                             "public_id": "BA-OTHER1", "tv": 0})
        finally:
            db.close()
    assert client.get("/api/auth/me", headers=auth(token)).status_code == 401


def test_staff_tenant_context_is_bound_before_querying_rls_staff(client, biz, monkeypatch):
    _, staff_headers = biz.staff_session()
    from app import security
    calls = []
    monkeypatch.setattr(security, "set_rls_business", lambda db, bid: calls.append(("bind", bid)))

    def inspect_statement(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT") and "FROM ft_staff" in statement:
            calls.append(("read", None))
            assert ("bind", biz.business_id) in calls

    event.listen(engine, "before_cursor_execute", inspect_statement)
    try:
        assert client.get("/api/auth/me", headers=staff_headers).status_code == 200
        assert any(kind == "read" for kind, _ in calls)
    finally:
        event.remove(engine, "before_cursor_execute", inspect_statement)
