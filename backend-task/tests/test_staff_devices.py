"""Owner-set passwords, one device at a time, and device binding."""
from tests.conftest import PASSWORD, auth, uniq


def test_owner_creates_staff_with_password(client, biz):
    s = biz.staff(name="Manju")
    assert s["role"] == "delivery" and s["signed_in"] is False
    listed = client.get("/api/staff", headers=biz.h).json()
    assert [x["name"] for x in listed] == ["Manju"]


def test_weak_password_and_duplicate_login(client, biz):
    r = client.post("/api/staff", headers=biz.h, json={"name": "A", "login_name": "anil", "password": "weak"})
    assert r.status_code == 400
    biz.staff(login="anil")
    r = client.post("/api/staff", headers=biz.h, json={"name": "B", "login_name": "ANIL", "password": PASSWORD})
    assert r.status_code == 400


def test_same_login_name_allowed_in_two_businesses(client, biz, other_biz):
    biz.staff(login="driver1")
    other_biz.staff(login="driver1")
    assert biz.login_staff("driver1")["business_id"] == biz.business_id
    assert other_biz.login_staff("driver1")["business_id"] == other_biz.business_id


def test_single_session_new_device_signs_out_old(client, biz):
    s = biz.staff()
    a = biz.login_staff(s["login_name"], device="phone-A-0001")
    assert client.get("/api/my/today", headers=auth(a["token"])).status_code == 200
    b = biz.login_staff(s["login_name"], device="phone-B-0002")
    assert b["signed_out_other_device"] is True
    r = client.get("/api/my/today", headers=auth(a["token"]))
    assert r.status_code == 401 and "another device" in r.json()["detail"]
    assert client.get("/api/my/today", headers=auth(b["token"])).status_code == 200


def test_bound_device_policy(client, biz):
    biz.settings(device_policy="bound")
    s = biz.staff()
    a = biz.login_staff(s["login_name"], device="phone-A-0001")
    r = client.post("/api/auth/staff/login", json={
        "business": biz.public_id, "login_name": s["login_name"], "password": PASSWORD,
        "device_id": "phone-B-0002"})
    assert r.status_code == 403 and "locked to another device" in r.json()["detail"]
    # same phone can sign in again
    a2 = biz.login_staff(s["login_name"], device="phone-A-0001")
    assert client.get("/api/my/today", headers=auth(a["token"])).status_code == 401  # superseded session
    # owner releases → new phone binds, old phone is out
    r = client.post(f"/api/staff/{s['id']}/release-device", headers=biz.h)
    assert r.status_code == 200 and r.json()["device_bound"] is False
    assert client.get("/api/my/today", headers=auth(a2["token"])).status_code == 401
    b = biz.login_staff(s["login_name"], device="phone-B-0002")
    assert client.get("/api/my/today", headers=auth(b["token"])).status_code == 200
    staff = client.get("/api/staff", headers=biz.h).json()[0]
    assert staff["device_bound"] is True


def test_staff_cannot_use_owner_endpoints(client, biz):
    _, h = biz.staff_session()
    assert client.get("/api/staff", headers=h).status_code == 403
    assert client.post("/api/shops", headers=h, json={"name": "x"}).status_code == 403
    assert client.get("/api/dashboard", headers=h).status_code == 403


def test_owner_cannot_use_staff_endpoints(client, biz):
    assert client.get("/api/my/today", headers=biz.h).status_code == 403


def test_staff_login_wrong_business(client, biz, other_biz):
    s = biz.staff()
    r = client.post("/api/auth/staff/login", json={
        "business": other_biz.public_id, "login_name": s["login_name"], "password": PASSWORD,
        "device_id": "phone-A-0001"})
    assert r.status_code == 401


def test_disable_and_password_reset_revoke_sessions(client, biz):
    s = biz.staff()
    tok = biz.login_staff(s["login_name"])["token"]
    assert client.patch(f"/api/staff/{s['id']}", headers=biz.h, json={"password": "Newpass99"}).status_code == 200
    assert client.get("/api/my/today", headers=auth(tok)).status_code == 401
    r = client.post("/api/auth/staff/login", json={"business": biz.public_id, "login_name": s["login_name"],
                                                   "password": "Newpass99", "device_id": "phone-A-0001"})
    tok = r.json()["token"]
    client.patch(f"/api/staff/{s['id']}", headers=biz.h, json={"is_active": False})
    assert client.get("/api/my/today", headers=auth(tok)).status_code == 401
    r = client.post("/api/auth/staff/login", json={"business": biz.public_id, "login_name": s["login_name"],
                                                   "password": "Newpass99", "device_id": "phone-A-0001"})
    assert r.status_code == 403


def test_owner_force_sign_out(client, biz):
    s, h = biz.staff_session()
    client.post(f"/api/staff/{s['id']}/sign-out", headers=biz.h)
    assert client.get("/api/my/today", headers=h).status_code == 401


def test_staff_logout(client, biz):
    _, h = biz.staff_session()
    assert client.post("/api/auth/logout", headers=h).status_code == 200
    assert client.get("/api/my/today", headers=h).status_code == 401


def test_owner_cannot_touch_other_business_staff(client, biz, other_biz):
    s = other_biz.staff()
    assert client.patch(f"/api/staff/{s['id']}", headers=biz.h, json={"name": "x"}).status_code == 404
    assert client.post(f"/api/staff/{s['id']}/release-device", headers=biz.h).status_code == 404


def test_login_throttle(client, biz):
    s = biz.staff()
    for _ in range(10):
        client.post("/api/auth/staff/login", json={"business": biz.public_id, "login_name": s["login_name"],
                                                   "password": "Wrong1234", "device_id": "phone-A-0001"})
    r = client.post("/api/auth/staff/login", json={"business": biz.public_id, "login_name": s["login_name"],
                                                   "password": PASSWORD, "device_id": "phone-A-0001"})
    assert r.status_code == 429


def test_login_by_owner_username_too(client, biz):
    s = biz.staff(login=uniq("drv"))
    r = client.post("/api/auth/staff/login", json={"business": biz.username, "login_name": s["login_name"],
                                                   "password": PASSWORD, "device_id": "phone-A-0001"})
    assert r.status_code == 200
