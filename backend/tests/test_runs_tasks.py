"""The working day: plan a route → deliver at each shop → points → dashboard."""
from datetime import date, datetime, timedelta, timezone

from app.billing_models import BillingCustomer
from app.db import SessionLocal
from tests.conftest import SHOP_LAT, SHOP_LNG, check_in, geo

FAR = SHOP_LAT + 0.01  # ≈ 1.1 km north


def _today():
    return datetime.now(timezone(timedelta(hours=5, minutes=30))).date().isoformat()


def _plan(client, biz, staff_id, stops, **kw):
    # Due at the end of today so "on time" holds whenever the suite runs.
    kw.setdefault("due_time", "23:59")
    r = client.post("/api/runs", headers=biz.h, json={"run_date": _today(), "staff_id": staff_id,
                                                      "name": "Jayanagar beat", "stops": stops, **kw})
    assert r.status_code == 201, r.text
    return r.json()


def test_full_delivery_day(client, biz):
    s, h = biz.staff_session("Kiran")
    a = biz.shop("Apollo Medicals")
    b = client.post("/api/shops", headers=biz.h, json={"name": "Unpinned Pharma", "phone": "9800000002"}).json()
    run = _plan(client, biz, s["id"], [
        {"shop_id": a["id"], "boxes": 4, "orders_count": 2, "reference": "INV-101, INV-102",
         "tasks": [{"task_type": "return_pickup", "title": "Collect expired returns", "points": 5}]},
        {"shop_id": b["id"], "boxes": 1, "orders_count": 1},
    ])
    assert run["boxes_planned"] == 5 and run["orders_count"] == 3 and run["stops_total"] == 2

    today = client.get("/api/my/today", headers=h).json()
    assert today["runs"][0]["stops"][0]["shop"]["phone"] == "9800000001"
    delivery_a = today["runs"][0]["stops"][0]["tasks"][0]
    stop_a = today["runs"][0]["stops"][0]["id"]
    stop_b = today["runs"][0]["stops"][1]["id"]

    # Not checked in → no field work.
    assert client.post(f"/api/run-stops/{stop_a}/arrive", headers=h, json={"geo": geo()}).status_code == 409
    check_in(client, h)
    # Task before arriving at the shop → refused.
    r = client.post(f"/api/tasks/{delivery_a['id']}/complete", headers=h, json={"geo": geo(), "boxes_delivered": 4})
    assert r.status_code == 409

    # Geofence enforced → arriving 1 km away is refused.
    biz.settings(geofence_enforced=True, geofence_radius_m=200)
    r = client.post(f"/api/run-stops/{stop_a}/arrive", headers=h, json={"geo": geo(lat=FAR)})
    assert r.status_code == 422 and "m from Apollo" in r.json()["detail"]
    r = client.post(f"/api/run-stops/{stop_a}/arrive", headers=h, json={"geo": geo(lat=SHOP_LAT + 0.0003)})
    assert r.status_code == 200 and r.json()["arrival_distance_m"] < 50
    assert client.get(f"/api/runs/{run['id']}", headers=h).json()["status"] == "in_progress"

    # Delivery needs the box count.
    r = client.post(f"/api/tasks/{delivery_a['id']}/complete", headers=h, json={"geo": geo()})
    assert r.status_code == 422
    r = client.post(f"/api/tasks/{delivery_a['id']}/complete", headers=h,
                    json={"geo": geo(), "boxes_delivered": 4, "note": "Given to pharmacist"})
    assert r.status_code == 200
    done = r.json()
    assert done["on_time"] is True and done["points_awarded"] == 10 and done["completion_distance_m"] < 5

    ret = [t for t in today["runs"][0]["stops"][0]["tasks"] if t["task_type"] == "return_pickup"][0]
    client.post(f"/api/tasks/{ret['id']}/complete", headers=h, json={"geo": geo()})
    stop = client.get(f"/api/runs/{run['id']}", headers=h).json()["stops"][0]
    assert stop["status"] == "done" and stop["boxes_delivered"] == 4

    # Unpinned shop: first arrival pins it (geofence cannot apply without a pin).
    r = client.post(f"/api/run-stops/{stop_b}/arrive", headers=h, json={"geo": geo(lat=FAR)})
    assert r.status_code == 200 and r.json()["shop"]["location_source"] == "staff"
    dt = r.json()["tasks"][0]
    client.post(f"/api/tasks/{dt['id']}/complete", headers=h, json={"geo": geo(lat=FAR), "boxes_delivered": 1})
    assert client.get(f"/api/runs/{run['id']}", headers=h).json()["status"] == "completed"

    d = client.get("/api/dashboard", headers=biz.h).json()
    assert d["deliveries"] == {"total": 2, "done": 2, "orders_sent": 3, "boxes_planned": 5, "boxes_delivered": 5}
    assert d["runs"]["completed"] == 1 and d["attendance"]["present"] == 1
    assert d["leaderboard"][0]["name"] == "Kiran"

    sc = client.get("/api/scorecard", headers=biz.h).json()["staff"][0]
    assert sc["deliveries_done"] == 2 and sc["boxes_delivered"] == 5 and sc["tasks_on_time"] == 3
    mine = client.get("/api/my/scorecard", headers=h).json()
    assert mine["points"] == sc["points"]


def test_skip_closed_shop(client, biz):
    s, h = biz.staff_session()
    a = biz.shop()
    run = _plan(client, biz, s["id"], [{"shop_id": a["id"], "boxes": 2}])
    check_in(client, h)
    stop_id = run["stops"][0]["id"]
    r = client.post(f"/api/run-stops/{stop_id}/skip", headers=h, json={"geo": geo(), "reason": "Shop closed"})
    assert r.status_code == 200 and r.json()["status"] == "skipped"
    assert client.get(f"/api/runs/{run['id']}", headers=biz.h).json()["status"] == "completed"


def test_late_task_earns_late_percentage(client, biz):
    s, h = biz.staff_session()
    biz.settings(late_points_pct=50)
    yesterday = (date.fromisoformat(_today()) - timedelta(days=1)).isoformat()
    t = client.post("/api/tasks", headers=biz.h, json={
        "title": "Collect cheque", "task_type": "payment_collect", "staff_id": s["id"],
        "due_date": yesterday, "due_time": "17:00", "points": 20, "amount_expected": 5000,
    }).json()
    assert t["overdue"] is True
    check_in(client, h)
    r = client.post(f"/api/tasks/{t['id']}/complete", headers=h, json={"geo": geo()})
    assert r.status_code == 422  # amount required
    r = client.post(f"/api/tasks/{t['id']}/complete", headers=h, json={"geo": geo(), "amount_collected": 5000})
    assert r.json()["on_time"] is False and r.json()["points_awarded"] == 10
    # Completed tasks are ledger entries — immutable.
    assert client.patch(f"/api/tasks/{t['id']}", headers=biz.h, json={"points": 99}).status_code == 409


def test_cannot_complete_someone_elses_task(client, biz):
    s1, h1 = biz.staff_session("One")
    s2, _ = biz.staff_session("Two")
    t = client.post("/api/tasks", headers=biz.h, json={"title": "x", "staff_id": s2["id"]}).json()
    check_in(client, h1)
    assert client.post(f"/api/tasks/{t['id']}/complete", headers=h1, json={"geo": geo()}).status_code == 404


def test_route_template_and_generate_today(client, biz):
    s = biz.staff()
    a, b = biz.shop("A"), biz.shop("B")
    wd = date.fromisoformat(_today()).isoweekday()
    r = client.post("/api/routes", headers=biz.h, json={
        "name": "Monday North", "weekdays": [wd], "default_staff_id": s["id"],
        "due_time": "17:30", "shop_ids": [b["id"], a["id"]]})
    assert r.status_code == 201 and [x["shop"]["name"] for x in r.json()["stops"]] == ["B", "A"]
    other_day = (wd % 7) + 1
    client.post("/api/routes", headers=biz.h, json={"name": "Other day", "weekdays": [other_day],
                                                    "default_staff_id": s["id"], "shop_ids": [a["id"]]})
    g = client.post("/api/runs/generate", headers=biz.h, json={}).json()
    assert [x["name"] for x in g["created"]] == ["Monday North"]
    g2 = client.post("/api/runs/generate", headers=biz.h, json={}).json()
    assert g2["created"] == [] and g2["skipped"][0]["reason"] == "already planned"
    runs = client.get("/api/runs", headers=biz.h).json()
    assert len(runs) == 1 and runs[0]["stops_total"] == 2
    # Owner adds boxes to a generated stop afterwards.
    rid = runs[0]["id"]
    r = client.post(f"/api/runs/{rid}/stops", headers=biz.h, json={"shop_id": a["id"], "boxes": 3})
    assert r.status_code == 409  # already on the run
    c = biz.shop("C")
    r = client.post(f"/api/runs/{rid}/stops", headers=biz.h, json={"shop_id": c["id"], "boxes": 3})
    assert r.status_code == 201 and r.json()["boxes_planned"] == 3


def test_reassign_run_moves_pending_tasks(client, biz):
    s1, s2 = biz.staff(name="One"), biz.staff(name="Two")
    a = biz.shop()
    run = _plan(client, biz, s1["id"], [{"shop_id": a["id"], "boxes": 1}])
    r = client.patch(f"/api/runs/{run['id']}", headers=biz.h, json={"staff_id": s2["id"]})
    assert r.json()["staff_name"] == "Two"
    assert r.json()["stops"][0]["tasks"][0]["staff_id"] == s2["id"]


def test_cancelled_run_blocks_work(client, biz):
    s, h = biz.staff_session()
    a = biz.shop()
    run = _plan(client, biz, s["id"], [{"shop_id": a["id"], "boxes": 1}])
    client.post(f"/api/runs/{run['id']}/cancel", headers=biz.h)
    check_in(client, h)
    r = client.post(f"/api/run-stops/{run['stops'][0]['id']}/arrive", headers=h, json={"geo": geo()})
    assert r.status_code == 409


def test_tenant_isolation(client, biz, other_biz):
    shop = other_biz.shop()
    s_other = other_biz.staff()
    assert client.patch(f"/api/shops/{shop['id']}", headers=biz.h, json={"name": "x"}).status_code == 404
    r = client.post("/api/runs", headers=biz.h, json={"run_date": _today(), "staff_id": s_other["id"],
                                                      "stops": [{"shop_id": shop["id"]}]})
    assert r.status_code == 404
    my_staff = biz.staff()
    r = client.post("/api/runs", headers=biz.h, json={"run_date": _today(), "staff_id": my_staff["id"],
                                                      "stops": [{"shop_id": shop["id"]}]})
    assert r.status_code == 404
    assert client.get("/api/shops", headers=biz.h).json() == []
    # Staff of business A cannot read business B's run.
    run = _plan(client, other_biz, s_other["id"], [{"shop_id": shop["id"], "boxes": 1}])
    _, h = biz.staff_session()
    assert client.get(f"/api/runs/{run['id']}", headers=h).status_code == 404


def test_import_shops_from_billing_customers(client, biz, other_biz):
    db = SessionLocal()
    mine = BillingCustomer(business_id=biz.business_id, name="Sri Balaji Medicals", phone="9811111111",
                           address="4th Block, Jayanagar")
    theirs = BillingCustomer(business_id=other_biz.business_id, name="Competitor Customer")
    db.add_all([mine, theirs])
    db.commit()
    mine_id, theirs_id = mine.id, theirs.id
    db.close()

    listed = client.get("/api/billing/customers", headers=biz.h).json()
    assert [c["name"] for c in listed] == ["Sri Balaji Medicals"]
    assert client.post("/api/shops/import-billing", headers=biz.h,
                       json={"customer_ids": [theirs_id]}).status_code == 404
    r = client.post("/api/shops/import-billing", headers=biz.h, json={"customer_ids": [mine_id]}).json()
    assert r["created"][0]["customer_id"] == mine_id and r["created"][0]["phone"] == "9811111111"
    again = client.post("/api/shops/import-billing", headers=biz.h, json={"customer_ids": [mine_id]}).json()
    assert again["created"] == [] and again["skipped_already_linked"] == 1


def test_run_for_another_day_cannot_be_worked_today(client, biz):
    s, h = biz.staff_session()
    a = biz.shop()
    tomorrow = (date.fromisoformat(_today()) + timedelta(days=1)).isoformat()
    r = client.post("/api/runs", headers=biz.h, json={"run_date": tomorrow, "staff_id": s["id"],
                                                      "stops": [{"shop_id": a["id"], "boxes": 1}]})
    run = r.json()
    check_in(client, h)
    r = client.post(f"/api/run-stops/{run['stops'][0]['id']}/arrive", headers=h, json={"geo": geo()})
    assert r.status_code == 409
