"""Deliveries and collections planned from the owner's billing invoices.

Billing rows are written straight into billing's tables (the mirror on SQLite,
billing's real schema in the contract job), the way billing itself would have.
"""
from datetime import date, timedelta

import pytest

from app.billing_models import BillingCustomer, BillingInvoice, BillingInvoiceLine
from app.db import SessionLocal
from app.timeutil import biz_today
from tests.conftest import check_in, geo


def _days_ago(n):
    return (date.fromisoformat(biz_today()) - timedelta(days=n)).isoformat()


def _customer(business_id, name="Sri Balaji Medicals"):
    db = SessionLocal()
    try:
        c = BillingCustomer(business_id=business_id, name=name, phone="9811111111")
        db.add(c)
        db.commit()
        return c.id
    finally:
        db.close()


def _bill(business_id, customer_id, number, *, days_ago=0, total=1000.0, paid=0.0,
          lines=(), invoice_type="B2B"):
    status = "Paid" if paid >= total else ("Partial" if paid > 0 else "Pending")
    db = SessionLocal()
    try:
        inv = BillingInvoice(business_id=business_id, customer_id=customer_id, invoice_id=number,
                             invoice_date=_days_ago(days_ago), status=status, invoice_type=invoice_type,
                             amount=total, total_amount=total, paid_amount=paid)
        db.add(inv)
        db.flush()
        for name, qty, unit, *returned in lines:
            db.add(BillingInvoiceLine(invoice_id=inv.id, product_name=name, quantity=qty, unit=unit,
                                      returned_qty=returned[0] if returned else 0.0, unit_price=10.0))
        db.commit()
        return inv.id
    finally:
        db.close()


@pytest.fixture
def linked(client, biz):
    """A shop imported from a billing customer, with a spread of bills."""
    cid = _customer(biz.business_id)
    shop = client.post("/api/shops/import-billing", headers=biz.h, json={"customer_ids": [cid]}).json()["created"][0]
    b = biz.business_id
    ids = {
        "boxes": _bill(b, cid, "INV-201", days_ago=1, total=2360.0,
                       lines=[("Paracetamol 500", 3, "Box"), ("Cough syrup", 2, "CTN", 1), ("Bandage", 40, "Nos")]),
        "strips": _bill(b, cid, "INV-202", total=500.0, paid=200.0, lines=[("Vitamin C", 10, "Strip")]),
        "old_due": _bill(b, cid, "INV-150", days_ago=90, total=800.0, paid=300.0),
        "old_paid": _bill(b, cid, "INV-140", days_ago=90, total=600.0, paid=600.0),
        "credit": _bill(b, cid, "CN-7", invoice_type="credit_note", total=100.0, paid=100.0),
    }
    ids["other_customer"] = _bill(b, _customer(b, "Someone Else"), "INV-203")
    return shop, cid, ids


def test_shop_lists_its_customers_bills(client, biz, linked):
    shop, cid, ids = linked
    r = client.get(f"/api/shops/{shop['id']}/billing-invoices", headers=biz.h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["customer_id"] == cid
    # Recent bills plus the old one still unpaid; not the paid old bill, the
    # credit note, or another customer's bill. Newest first.
    assert [i["number"] for i in body["invoices"]] == ["INV-202", "INV-201", "INV-150"]
    by = {i["number"]: i for i in body["invoices"]}
    assert by["INV-201"]["boxes"] == 4  # 3 Box + (2 − 1 returned) CTN; "Nos" lines are not boxes
    assert by["INV-202"]["boxes"] is None  # strips only: the owner types the boxes
    assert by["INV-201"]["balance_due"] == 2360.0
    assert by["INV-202"]["balance_due"] == 300.0 and by["INV-202"]["status"] == "Partial"
    assert by["INV-150"]["balance_due"] == 500.0
    assert by["INV-201"]["lines"][1] == {"product_name": "Cough syrup", "quantity": 1.0, "unit": "CTN"}
    assert all(i["tasks"] == [] for i in body["invoices"])

    wide = client.get(f"/api/shops/{shop['id']}/billing-invoices", headers=biz.h, params={"days": 120}).json()
    assert "INV-140" in [i["number"] for i in wide["invoices"]]


def test_run_stop_from_invoices_plans_delivery_and_collection(client, biz, linked):
    shop, _, ids = linked
    s, h = biz.staff_session("Kiran")
    pick = [ids["boxes"], ids["strips"]]
    r = client.post("/api/runs", headers=biz.h, json={
        "run_date": biz_today(), "staff_id": s["id"], "due_time": "23:59",
        "stops": [{"shop_id": shop["id"], "invoice_ids": pick, "collect_due": True}],
    })
    assert r.status_code == 201, r.text
    stop = r.json()["stops"][0]
    delivery, collect = stop["tasks"]
    assert delivery["task_type"] == "delivery"
    assert delivery["boxes_planned"] == 4 and delivery["orders_count"] == 2
    assert delivery["reference"] == "INV-201, INV-202"
    assert delivery["title"] == f"Deliver 4 box(es) to {shop['name']}"
    assert [i["number"] for i in delivery["invoices"]] == ["INV-201", "INV-202"]
    assert collect["task_type"] == "payment_collect"
    assert collect["amount_expected"] == 2660.0  # 2360 + (500 − 200)
    assert [i["balance_due"] for i in collect["invoices"]] == [2360.0, 300.0]

    listed = {i["id"]: i for i in client.get(f"/api/shops/{shop['id']}/billing-invoices", headers=biz.h).json()["invoices"]}
    assert {t["task_type"] for t in listed[ids["boxes"]]["tasks"]} == {"delivery", "payment_collect"}

    # The staff member sees which bills they carry and completes as before.
    check_in(client, h)
    assert client.post(f"/api/run-stops/{stop['id']}/arrive", headers=h, json={"geo": geo()}).status_code == 200
    mine = client.get("/api/my/tasks", headers=h).json()
    assert [i["number"] for i in mine[0]["invoices"]] == ["INV-201", "INV-202"]
    done = client.post(f"/api/tasks/{delivery['id']}/complete", headers=h,
                       json={"geo": geo(), "boxes_delivered": 4})
    assert done.status_code == 200, done.text


def test_a_bill_is_delivered_once_until_its_task_is_cancelled(client, biz, linked):
    shop, _, ids = linked
    s = biz.staff()
    plan = {"run_date": biz_today(), "staff_id": s["id"],
            "stops": [{"shop_id": shop["id"], "invoice_ids": [ids["boxes"]]}]}
    run = client.post("/api/runs", headers=biz.h, json=plan).json()
    again = client.post("/api/runs", headers=biz.h, json=plan)
    assert again.status_code == 409 and "INV-201 is already on delivery task" in again.json()["detail"]
    # A collection for the same bill is a different job, so it is allowed.
    r = client.post("/api/tasks", headers=biz.h, json={
        "title": "Collect", "task_type": "payment_collect", "staff_id": s["id"],
        "shop_id": shop["id"], "invoice_ids": [ids["boxes"]]})
    assert r.status_code == 201, r.text

    assert client.post(f"/api/runs/{run['id']}/cancel", headers=biz.h).status_code == 200
    assert client.post("/api/runs", headers=biz.h, json=plan).status_code == 201


def test_task_from_invoices_keeps_what_the_owner_typed(client, biz, linked):
    shop, _, ids = linked
    s = biz.staff()
    r = client.post("/api/tasks", headers=biz.h, json={
        "title": "Collect dues", "task_type": "payment_collect", "staff_id": s["id"], "shop_id": shop["id"],
        "invoice_ids": [ids["old_due"], ids["strips"], ids["old_due"]]})
    assert r.status_code == 201, r.text
    t = r.json()
    assert t["amount_expected"] == 800.0 and t["reference"] == "INV-150, INV-202"
    assert len(t["invoices"]) == 2  # the repeat is dropped

    r = client.post("/api/tasks", headers=biz.h, json={
        "title": "Deliver", "task_type": "delivery", "staff_id": s["id"], "shop_id": shop["id"],
        "boxes_planned": 9, "reference": "Rush order", "invoice_ids": [ids["boxes"]]}).json()
    assert r["boxes_planned"] == 9 and r["reference"] == "Rush order" and r["orders_count"] == 1


@pytest.mark.parametrize("key, status, detail", [
    ("other_customer", 422, "different customer"),
    ("credit", 422, "credit note"),
])
def test_bills_must_belong_to_the_shop(client, biz, linked, key, status, detail):
    shop, _, ids = linked
    s = biz.staff()
    r = client.post("/api/tasks", headers=biz.h, json={
        "title": "Deliver", "task_type": "delivery", "staff_id": s["id"], "shop_id": shop["id"],
        "invoice_ids": [ids[key]]})
    assert r.status_code == status and detail in r.json()["detail"]


def test_invoices_need_a_linked_shop(client, biz, linked):
    _, _, ids = linked
    s = biz.staff()
    manual = biz.shop("Walk-in Pharma")
    assert client.get(f"/api/shops/{manual['id']}/billing-invoices", headers=biz.h).json()["invoices"] == []
    r = client.post("/api/tasks", headers=biz.h, json={
        "title": "Deliver", "task_type": "delivery", "staff_id": s["id"], "shop_id": manual["id"],
        "invoice_ids": [ids["boxes"]]})
    assert r.status_code == 422 and "not linked to a billing customer" in r.json()["detail"]
    r = client.post("/api/tasks", headers=biz.h, json={
        "title": "Deliver", "task_type": "delivery", "staff_id": s["id"], "invoice_ids": [ids["boxes"]]})
    assert r.status_code == 422
    r = client.post("/api/runs", headers=biz.h, json={
        "run_date": biz_today(), "staff_id": s["id"], "stops": [{"shop_id": manual["id"], "collect_due": True}]})
    assert r.status_code == 422


def test_link_an_existing_shop_to_a_billing_customer(client, biz, other_biz, linked):
    imported, linked_cid, _ = linked
    shop = biz.shop("Hand-made Shop")
    cid = _customer(biz.business_id, "Hand-made Shop Pvt Ltd")
    r = client.patch(f"/api/shops/{shop['id']}", headers=biz.h, json={"customer_id": cid})
    assert r.status_code == 200 and r.json()["customer_id"] == cid
    assert client.patch(f"/api/shops/{shop['id']}", headers=biz.h, json={"customer_id": linked_cid}).status_code == 409
    theirs = _customer(other_biz.business_id)
    assert client.patch(f"/api/shops/{shop['id']}", headers=biz.h, json={"customer_id": theirs}).status_code == 404
    # Editing other fields leaves the link alone; null unlinks.
    assert client.patch(f"/api/shops/{shop['id']}", headers=biz.h, json={"area": "Jayanagar"}).json()["customer_id"] == cid
    assert client.patch(f"/api/shops/{shop['id']}", headers=biz.h, json={"customer_id": None}).json()["customer_id"] is None
    assert client.patch(f"/api/shops/{imported['id']}", headers=biz.h, json={"name": "Renamed"}).json()["customer_id"] == linked_cid


def test_other_business_cannot_see_or_use_the_bills(client, biz, other_biz, linked):
    shop, _, ids = linked
    assert client.get(f"/api/shops/{shop['id']}/billing-invoices", headers=other_biz.h).status_code == 404
    their_cid = _customer(other_biz.business_id)
    their_shop = client.post("/api/shops/import-billing", headers=other_biz.h,
                             json={"customer_ids": [their_cid]}).json()["created"][0]
    s = other_biz.staff()
    r = client.post("/api/tasks", headers=other_biz.h, json={
        "title": "Deliver", "task_type": "delivery", "staff_id": s["id"], "shop_id": their_shop["id"],
        "invoice_ids": [ids["boxes"]]})
    assert r.status_code == 404
