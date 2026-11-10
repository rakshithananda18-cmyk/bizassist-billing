"""GPS trail (duty-only, throttled), live view, and shop requests."""
from datetime import timedelta, timezone

from app.db import utc_now
from tests.conftest import SHOP_LAT, check_in, geo


def test_pings_only_while_on_duty_and_throttled(client, biz):
    s, h = biz.staff_session("Tracker")
    r = client.post("/api/track/pings", headers=h, json={"pings": [geo()]}).json()
    assert r["stored"] == 0 and r["reason"] == "off duty"
    check_in(client, h)  # the check-in itself is a fix
    r = client.post("/api/track/pings", headers=h, json={"pings": [geo(lat=SHOP_LAT + 0.001)]}).json()
    assert r["stored"] == 0  # within half the interval of the check-in fix

    base = utc_now().replace(tzinfo=timezone.utc)
    batch = [geo(lat=SHOP_LAT + i * 0.001, client_time=(base + timedelta(seconds=i * 60)).isoformat())
             for i in range(5)]
    batch.append(geo(accuracy=5000))  # junk fix dropped
    r = client.post("/api/track/pings", headers=h, json={"pings": batch}).json()
    assert r["stored"] == 5 and r["ignored"] == 1

    trail = client.get(f"/api/track/trail?staff_id={s['id']}", headers=biz.h).json()["points"]
    assert trail[0]["event"] == "check_in" and len(trail) == 6

    live = client.get("/api/track/live", headers=biz.h).json()["staff"][0]
    assert live["duty"] == "on_duty" and abs(live["location"]["lat"] - (SHOP_LAT + 0.004)) < 1e-9


def test_trail_is_owner_scoped(client, biz, other_biz):
    s = other_biz.staff()
    assert client.get(f"/api/track/trail?staff_id={s['id']}", headers=biz.h).status_code == 404


def test_shop_requirement_list(client, biz):
    s, h = biz.staff_session()
    shop = biz.shop("Sanjeevini Medicals")
    body = {"geo": geo(), "shop_id": shop["id"], "kind": "requirement",
            "items": [{"name": "Dolo 650", "qty": 20, "unit": "Strip"},
                      {"name": "ORS sachets", "qty": 2, "unit": "Box"}],
            "note": "Needs before Friday"}
    assert client.post("/api/requests", headers=h, json=body).status_code == 409  # not checked in
    check_in(client, h)
    r = client.post("/api/requests", headers=h, json=body)
    assert r.status_code == 201 and r.json()["items"][0]["name"] == "Dolo 650"
    rid = r.json()["id"]
    listed = client.get("/api/requests?status=new", headers=biz.h).json()
    assert listed[0]["shop_name"] == "Sanjeevini Medicals" and listed[0]["location"]["lat"] == geo()["lat"]
    assert client.patch(f"/api/requests/{rid}", headers=biz.h, json={"status": "acknowledged"}).json()["status"] == "acknowledged"
    assert client.get("/api/dashboard", headers=biz.h).json()["open_requests"] == 0
    assert len(client.get("/api/my/requests", headers=h).json()) == 1


def test_activity_feed_records_location(client, biz):
    _, h = biz.staff_session("Feed")
    check_in(client, h)
    feed = client.get("/api/activity", headers=biz.h).json()
    assert feed[0]["action"] == "attendance.check_in" and feed[0]["location"] is not None
    assert feed[0]["actor"] == "Feed"
