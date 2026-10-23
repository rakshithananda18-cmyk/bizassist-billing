"""Test harness: one throwaway SQLite DB per session; every test makes its own
business(es) with unique names, so tests are isolated the same way tenants are.

Parallel runs (`run_tests.bat fast` → pytest-xdist) need nothing extra: each
worker is its own process, so it gets its own temp dir and SQLite file. Keep
Postgres runs (TASK_TEST_DATABASE_URL) serial — workers would race the
startup migration on the one shared database."""
import json
import os
import tempfile
import time
import uuid
from datetime import datetime

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

from app import db as app_db  # noqa: E402
from app.main import app  # noqa: E402
from app.timeutil import biz_local_to_utc, biz_today  # noqa: E402

# ── The business clock: midday IST, whatever the wall clock says ─────────────
# Tests plan today's runs due at 23:59 and work them at once. Near midnight IST
# that work would be late, or the run would belong to yesterday by the time it
# is worked. So the app's clock (app.db.utc_now, read by every module and
# column default) starts at 12:00 IST on today's business date and ticks from
# there. Tests read "now" and "today" through the app (utc_now, biz_today),
# never from the OS. Tokens are signed on this clock but PyJWT checks them on
# the real one; the gap is under 12 h and they live 14 h, so they stay valid.
if not app_db.CLOCK_OFFSET:  # once: tests import this file again as tests.conftest
    _real_now = app_db.utc_now()
    app_db.CLOCK_OFFSET = biz_local_to_utc(biz_today(_real_now), "12:00") - _real_now

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


# ── test_results.json — same file and schema as billing's tests/conftest.py ──
# Read live by serve_dashboard.py (run_tests.ps1 opens it). Only the controlling
# process writes: under pytest-xdist every worker's reports reach it anyway,
# and workers writing too would clobber each other.

_RESULTS_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "test_results.json")
_IS_XDIST_WORKER = "PYTEST_XDIST_WORKER" in os.environ
_results = {
    "summary": {"total": 0, "passed": 0, "failed": 0, "skipped": 0, "duration": 0.0,
                "timestamp": "", "status": "running"},
    "tests": [],
}
_session_start = 0.0


def _write_results():
    if _IS_XDIST_WORKER:
        return
    summary, tests = _results["summary"], _results["tests"]
    for outcome in ("passed", "failed", "skipped"):
        summary[outcome] = sum(1 for t in tests if t["outcome"] == outcome)
    summary["duration"] = round(time.time() - _session_start, 3)
    try:
        tmp = _RESULTS_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_results, f, indent=2)
        os.replace(tmp, _RESULTS_PATH)  # the dashboard never reads half a file
    except OSError:
        pass


def pytest_sessionstart(session):
    global _session_start
    _session_start = time.time()
    _results["summary"].update(timestamp=datetime.now().isoformat(), status="running", total=0)
    _results["tests"] = []
    _write_results()


def pytest_collection_finish(session):
    if session.items:  # serial run; under xdist the workers collect
        _results["summary"]["total"] = len(session.items)
        _write_results()


@pytest.hookimpl(optionalhook=True)
def pytest_xdist_node_collection_finished(node, ids):
    _results["summary"]["total"] = len(ids)
    _write_results()


def pytest_runtest_logreport(report):
    if not (report.when == "call" or (report.when == "setup" and (report.failed or report.skipped))):
        return
    outcome = "failed" if report.failed else "skipped" if report.skipped else "passed"
    _results["tests"].append({
        "nodeid": report.nodeid,
        "name": report.location[2] if report.location else report.nodeid,
        "file": report.location[0] if report.location else "",
        "line": report.location[1] if report.location else 0,
        "outcome": outcome,
        "duration": report.duration,
        "traceback": str(report.longrepr) if report.failed else None,
        "longrepr": report.longreprtext if report.failed else None,
    })
    _write_results()


def pytest_sessionfinish(session, exitstatus):
    _results["summary"]["total"] = len(_results["tests"])
    _results["summary"]["status"] = "completed"
    _write_results()
