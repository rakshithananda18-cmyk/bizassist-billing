"""Attendance: server time, mandatory location, lateness, points."""
from datetime import datetime, timedelta, timezone

from tests.conftest import check_in, geo


def test_location_is_mandatory(client, biz):
    _, h = biz.staff_session()
    assert client.post("/api/attendance/check-in", headers=h, json={}).status_code == 422
    r = client.post("/api/attendance/check-in", headers=h, json={"geo": {"lat": 12.9, "lng": 77.5}})
    assert r.status_code == 422 and "accuracy" in r.json()["detail"].lower()
    r = client.post("/api/attendance/check-in", headers=h, json={"geo": geo(accuracy=900)})
    assert r.status_code == 422 and "imprecise" in r.json()["detail"]
    r = client.post("/api/attendance/check-in", headers=h, json={"geo": geo(lat=0, lng=0)})
    assert r.status_code == 422
    r = client.post("/api/attendance/check-in", headers=h, json={"geo": geo(lat=91)})
    assert r.status_code == 422


def test_check_in_uses_server_time_not_phone_time(client, biz):
    _, h = biz.staff_session()
    fake = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
    att = check_in(client, h, client_time=fake)
    server = datetime.fromisoformat(att["check_in_at"].replace("Z", "+00:00"))
    assert abs((datetime.now(timezone.utc) - server).total_seconds()) < 60
    assert att["client_clock_skew_s"] < -3 * 3600 + 120  # phone was 3h behind; recorded as evidence
    assert att["check_in_location"]["lat"] == geo()["lat"]


def test_double_check_in_and_checkout_rules(client, biz):
    _, h = biz.staff_session()
    check_in(client, h)
    assert client.post("/api/attendance/check-in", headers=h, json={"geo": geo()}).status_code == 409
    assert client.post("/api/attendance/check-out", headers=h, json={"geo": geo()}).status_code == 200
    assert client.post("/api/attendance/check-out", headers=h, json={"geo": geo()}).status_code == 409
    me = client.get("/api/attendance/me", headers=h).json()
    assert me["attendance"]["check_out_at"] is not None


def test_late_check_in_and_on_time_points(client, biz):
    # workday 00:00 with no grace → anyone checking in now is late (unless it is 00:00 exactly)
    biz.settings(workday_start="00:00", late_grace_min=0, on_time_checkin_points=5)
    _, h = biz.staff_session("Late")
    att = check_in(client, h)
    now_local = datetime.now(timezone(timedelta(hours=5, minutes=30)))
    if now_local.hour or now_local.minute:
        assert att["status"] == "late" and att["minutes_late"] > 0 and att["points_awarded"] == 0

    biz.settings(workday_start="23:59", late_grace_min=0)
    _, h2 = biz.staff_session("Early")
    att2 = check_in(client, h2)
    if not (now_local.hour == 23 and now_local.minute == 59):
        assert att2["status"] == "present" and att2["points_awarded"] == 5


def test_register_lists_present_and_absent(client, biz):
    _, h = biz.staff_session("Present")
    biz.staff(name="Absent")
    check_in(client, h)
    reg = client.get("/api/attendance", headers=biz.h).json()
    assert [p["staff_name"] for p in reg["present"]] == ["Present"]
    assert [a["name"] for a in reg["absent"]] == ["Absent"]


def test_owner_cannot_check_in(client, biz):
    assert client.post("/api/attendance/check-in", headers=biz.h, json={"geo": geo()}).status_code == 403
