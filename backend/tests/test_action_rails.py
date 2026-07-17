"""
tests/test_action_rails.py — Phase-0 write-tool safety rails (MASTER_REVIEW §3.2 #4).
=====================================================================================
The three rails around gated actions:

  1. confirm token  — execute refuses a missing/tampered/expired/cross-user/
                      cross-params token; a previewed token verifies.
  2. idempotency    — the same X-Client-Request-Id never executes twice; the
                      stored response is replayed verbatim.
  3. daily caps     — the dispatcher refuses once today's ActionLog rows for
                      (business, action) reach the cap; route surfaces 429.
"""
import os
import sys

os.environ["DATABASE_URL"] = "sqlite:///./test_bizassist.db"
os.environ["GROQ_API_KEY"] = "mock_groq_api_key"

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, backend_path)

import uuid
import pytest
from fastapi.testclient import TestClient

import services.actions as actions
from services import action_rails
from database.db import SessionLocal
from database.models import Base, Invoice, Customer, ActionLog, Inventory
from main_groq import app

client = TestClient(app)
BID = 770022  # only for token unit tests; route tests use a signed-up owner


# ── fixtures ─────────────────────────────────────────────────────────────────

def _seed_business(bid):
    db = SessionLocal()
    try:
        db.add(Customer(business_id=bid, name="Acme", email="acme@example.com"))
        db.add(Invoice(business_id=bid, invoice_id="R-1", customer="Acme",
                       amount=1200, status="Overdue", due_date="2024-01-01"))
        db.commit()
    finally:
        db.close()


@pytest.fixture()
def owner():
    r = client.post("/signup", json={
        "username": f"rails_{uuid.uuid4().hex[:8]}",
        "password": "Password123!",
        "business_name": "Rails Biz",
    })
    assert r.status_code == 200, r.text
    d = r.json()
    _seed_business(d["id"])
    return {"headers": {"Authorization": f"Bearer {d['token']}"}, "bid": d["id"]}


# ── 1. confirm token unit behaviour ──────────────────────────────────────────

def test_token_roundtrip_ok():
    t = action_rails.mint_confirm_token(BID, "send_payment_reminders", {"days": 30})
    ok, reason = action_rails.verify_confirm_token(t, BID, "send_payment_reminders", {"days": 30})
    assert ok and reason == "ok"


def test_token_binds_params_exactly():
    t = action_rails.mint_confirm_token(BID, "send_payment_reminders", {"days": 30})
    ok, reason = action_rails.verify_confirm_token(t, BID, "send_payment_reminders", {"days": 60})
    assert not ok and reason == "mismatch"


def test_token_binds_action_and_user():
    t = action_rails.mint_confirm_token(BID, "send_payment_reminders", None)
    assert action_rails.verify_confirm_token(t, BID, "mark_invoice_paid", None)[0] is False
    assert action_rails.verify_confirm_token(t, BID + 1, "send_payment_reminders", None)[0] is False


def test_token_expiry_and_malformed():
    t = action_rails.mint_confirm_token(BID, "x", None, ttl_secs=-1)
    assert action_rails.verify_confirm_token(t, BID, "x", None) == (False, "expired")
    assert action_rails.verify_confirm_token(None, BID, "x", None) == (False, "missing")
    assert action_rails.verify_confirm_token("nodot", BID, "x", None) == (False, "missing")
    assert action_rails.verify_confirm_token("abc.def", BID, "x", None) == (False, "malformed")


def test_param_canonicalization_is_order_stable():
    t = action_rails.mint_confirm_token(BID, "a", {"b": 1, "a": 2})
    ok, _ = action_rails.verify_confirm_token(t, BID, "a", {"a": 2, "b": 1})
    assert ok


# ── 2. route: preview mints, execute enforces ────────────────────────────────

def test_preview_returns_confirm_token(owner):
    r = client.post("/action/preview", headers=owner["headers"],
                    json={"action": "send_payment_reminders"})
    assert r.status_code == 200, r.text
    assert "." in r.json().get("confirm_token", "")


def test_execute_without_token_is_428(owner):
    r = client.post("/action/execute", headers=owner["headers"],
                    json={"action": "send_payment_reminders"})
    assert r.status_code == 428
    assert "confirm" in r.json()["detail"].lower()


def test_execute_with_tampered_token_is_428(owner):
    r = client.post("/action/preview", headers=owner["headers"],
                    json={"action": "send_payment_reminders"})
    token = r.json()["confirm_token"]
    bad = token[:-4] + ("0000" if token[-4:] != "0000" else "1111")
    r = client.post("/action/execute", headers=owner["headers"],
                    json={"action": "send_payment_reminders", "confirm_token": bad})
    assert r.status_code == 428


def test_preview_then_execute_succeeds(owner):
    r = client.post("/action/preview", headers=owner["headers"],
                    json={"action": "send_payment_reminders"})
    token = r.json()["confirm_token"]
    r = client.post("/action/execute", headers=owner["headers"],
                    json={"action": "send_payment_reminders", "confirm_token": token})
    assert r.status_code == 200, r.text
    assert r.json()["source"] == "action"


def test_escape_hatch_disables_enforcement(owner, monkeypatch):
    monkeypatch.setenv("ACTION_CONFIRM_REQUIRED", "0")
    r = client.post("/action/execute", headers=owner["headers"],
                    json={"action": "send_payment_reminders"})
    assert r.status_code == 200, r.text


# ── 3. idempotency: X-Client-Request-Id replays, never re-executes ──────────

def _logged_rows(bid):
    db = SessionLocal()
    try:
        return db.query(ActionLog).filter(ActionLog.business_id == bid).count()
    finally:
        db.close()


def test_same_request_id_executes_once(owner):
    r = client.post("/action/preview", headers=owner["headers"],
                    json={"action": "send_payment_reminders"})
    token = r.json()["confirm_token"]
    hdrs = {**owner["headers"], "X-Client-Request-Id": "rails-test-0001"}
    body = {"action": "send_payment_reminders", "confirm_token": token}

    r1 = client.post("/action/execute", headers=hdrs, json=body)
    assert r1.status_code == 200, r1.text
    rows_after_first = _logged_rows(owner["bid"])

    r2 = client.post("/action/execute", headers=hdrs, json=body)
    assert r2.status_code == 200
    assert _logged_rows(owner["bid"]) == rows_after_first          # nothing re-executed
    assert r2.json()["response"] == r1.json()["response"]  # replayed verbatim


def test_different_request_ids_execute_independently(owner):
    for rid in ("rails-test-0002", "rails-test-0003"):
        r = client.post("/action/preview", headers=owner["headers"],
                        json={"action": "send_payment_reminders"})
        token = r.json()["confirm_token"]
        r = client.post("/action/execute",
                        headers={**owner["headers"], "X-Client-Request-Id": rid},
                        json={"action": "send_payment_reminders", "confirm_token": token})
        assert r.status_code == 200


# ── 4. daily caps ────────────────────────────────────────────────────────────

def test_cap_env_override_and_default(monkeypatch):
    assert action_rails.daily_cap("email_reminder_digest") == 5
    monkeypatch.setenv("ACTION_DAILY_CAP_EMAIL_REMINDER_DIGEST", "9")
    assert action_rails.daily_cap("email_reminder_digest") == 9
    monkeypatch.setenv("ACTION_DAILY_CAP_DEFAULT", "77")
    assert action_rails.daily_cap("some_future_action") == 77


def test_dispatcher_refuses_over_cap(owner, monkeypatch):
    monkeypatch.setenv("ACTION_DAILY_CAP_SEND_PAYMENT_REMINDERS", "1")
    bid = owner["bid"]
    r1 = actions.execute("send_payment_reminders", bid, {})
    assert r1 is not None and r1.get("error") != "daily_cap_reached"
    assert _logged_rows(bid) >= 1
    r2 = actions.execute("send_payment_reminders", bid, {})
    assert r2.get("error") == "daily_cap_reached"
    assert r2["ok"] is False


def test_route_surfaces_cap_as_429(owner, monkeypatch):
    monkeypatch.setenv("ACTION_DAILY_CAP_SEND_PAYMENT_REMINDERS", "0")
    r = client.post("/action/preview", headers=owner["headers"],
                    json={"action": "send_payment_reminders"})
    token = r.json()["confirm_token"]
    r = client.post("/action/execute", headers=owner["headers"],
                    json={"action": "send_payment_reminders", "confirm_token": token})
    assert r.status_code == 429
    assert "limit" in r.json()["detail"].lower()
