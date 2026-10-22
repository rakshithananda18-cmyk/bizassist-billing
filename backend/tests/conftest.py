"""Test harness: one throwaway SQLite DB per session; every test makes its own
business(es) with unique names, so tests are isolated the same way tenants are."""
import os
import tempfile
import uuid

_TMP = tempfile.mkdtemp(prefix="bizassist_task_test_")
# TASK_TEST_DATABASE_URL runs the suite on Postgres (CI, or a DB already migrated
# by billing's own Alembic chain — set TASK_TEST_BILLING_SCHEMA=external then).
os.environ["DATABASE_URL"] = os.environ.get("TASK_TEST_DATABASE_URL") or \
    f"sqlite:///{os.path.join(_TMP, 'test_task.db')}"
assert "test" in os.environ["DATABASE_URL"].lower(), "tests must run on a database whose URL contains 'test'"
os.environ.setdefault("JWT_SECRET", "test-secret-0123456789abcdef0123456789abcdef")
EXTERNAL_BILLING_SCHEMA = os.environ.get("TASK_TEST_BILLING_SCHEMA") == "external"
os.environ["TASK_CREATE_BILLING_MIRROR"] = "0" if EXTERNAL_BILLING_SCHEMA else "1"
os.environ["LOG_LEVEL"] = "WARNING"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

# Bengaluru, near a shop pin used across tests.
SHOP_LAT, SHOP_LNG = 12.971600, 77.594600
PASSWORD = "Fieldw0rk!"


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


def geo(lat=SHOP_LAT, lng=SHOP_LNG, accuracy=12.0, **extra):
    return {"lat": lat, "lng": lng, "accuracy": accuracy, **extra}


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def uniq(prefix="biz"):
    return f"{prefix}{uuid.uuid4().hex[:8]}"


class Biz:
    """An owner account plus helpers to build staff and log them in."""

    def __init__(self, client):
        self.c = client
        self.username = uniq("owner")
        r = client.post("/api/auth/owner/signup", json={
            "username": self.username, "password": PASSWORD, "business_name": "Sri Medicals",
        })
        assert r.status_code == 201, r.text
        body = r.json()
        self.token = body["token"]
        self.business_id = body["business_id"]
        self.public_id = body["public_id"]
        self.h = auth(self.token)

    def staff(self, name="Ravi", login=None, role="delivery"):
        login = login or uniq("agent")
        r = self.c.post("/api/staff", headers=self.h, json={
            "name": name, "login_name": login, "password": PASSWORD, "role": role,
        })
        assert r.status_code == 201, r.text
        return r.json()

    def login_staff(self, login, device="device-aaaa-1111", expect=200):
        r = self.c.post("/api/auth/staff/login", json={
            "business": self.public_id, "login_name": login, "password": PASSWORD,
            "device_id": device, "device_label": "Test phone",
        })
        assert r.status_code == expect, r.text
        return r.json()

    def staff_session(self, name="Ravi"):
        s = self.staff(name=name)
        tok = self.login_staff(s["login_name"])["token"]
        return s, auth(tok)

    def settings(self, **kw):
        r = self.c.patch("/api/settings", headers=self.h, json=kw)
        assert r.status_code == 200, r.text
        return r.json()

    def shop(self, name="Lakshmi Medicals", lat=SHOP_LAT, lng=SHOP_LNG, phone="9800000001"):
        r = self.c.post("/api/shops", headers=self.h, json={"name": name, "lat": lat, "lng": lng, "phone": phone})
        assert r.status_code == 201, r.text
        return r.json()


@pytest.fixture
def biz(client):
    return Biz(client)


@pytest.fixture
def other_biz(client):
    return Biz(client)


def check_in(client, h, **kw):
    r = client.post("/api/attendance/check-in", headers=h, json={"geo": geo(**kw)})
    assert r.status_code == 201, r.text
    return r.json()
