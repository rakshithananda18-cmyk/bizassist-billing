"""
test_import_preview_contacts.py
===============================
Parity check for the customer/vendor import approval gate (mirrors the
products preview flow). `?preview=1` must:
  - write NOTHING to the DB,
  - return normalized rows,
  - flag duplicates (by name / phone) in `problems`.
A subsequent flag-less POST commits.
"""
import os
import sys
import uuid

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, backend_path)

db_file = os.path.join(backend_path, "test_bizassist.db").replace("\\", "/")
os.environ["DATABASE_URL"] = f"sqlite:///{db_file}"
os.environ["GROQ_API_KEY"] = "mock_groq_api_key"

import pytest
from fastapi.testclient import TestClient
from main_groq import app
from database.db import SessionLocal
from database.models import Base, Customer, Vendor

client = TestClient(app)


@pytest.fixture(scope="module", autouse=True)
def _schema():
    if os.path.exists(db_file):
        try:
            os.remove(db_file)
        except Exception:
            pass
    db = SessionLocal()
    try:
        Base.metadata.create_all(bind=db.get_bind())
    finally:
        db.close()


@pytest.fixture(scope="module")
def owner():
    r = client.post("/signup", json={
        "username": f"own_{uuid.uuid4().hex[:6]}",
        "password": "Password123!",
        "business_name": "Preview Biz",
    })
    assert r.status_code == 200, r.text
    return {"headers": {"Authorization": f"Bearer {r.json()['token']}"}, "bid": r.json()["id"]}


@pytest.fixture(autouse=True)
def _clean(owner):
    db = SessionLocal()
    try:
        db.query(Customer).delete()
        db.query(Vendor).delete()
        db.commit()
    finally:
        db.close()


def _count(model, bid):
    db = SessionLocal()
    try:
        return db.query(model).filter(model.business_id == bid).count()
    finally:
        db.close()


def test_customer_preview_writes_nothing_then_commits(owner):
    payload = {"items": [
        {"name": "Ramesh Traders", "phone": "9990001111"},
        {"name": "", "phone": "8880002222"},  # invalid: no name
    ]}
    # preview → no writes, problems surfaced
    pv = client.post("/import/customers?preview=1", headers=owner["headers"], json=payload)
    assert pv.status_code == 200, pv.text
    body = pv.json()
    assert body["preview"] is True
    assert body["count"] == 2
    assert _count(Customer, owner["bid"]) == 0  # nothing landed
    problems = [row["problems"] for row in body["items"]]
    assert problems[0] == []           # first row clean
    assert "name required" in problems[1]

    # commit only the valid row
    commit = client.post("/import/customers", headers=owner["headers"],
                         json={"items": [payload["items"][0]]})
    assert commit.status_code == 200, commit.text
    assert _count(Customer, owner["bid"]) == 1


def test_customer_preview_flags_duplicate(owner):
    client.post("/import/customers", headers=owner["headers"],
                json={"items": [{"name": "Dup Co", "phone": "9111122223"}]})
    pv = client.post("/import/customers?preview=1", headers=owner["headers"],
                     json={"items": [
                         {"name": "Dup Co", "phone": "5000000000"},        # dup name
                         {"name": "Fresh Co", "phone": "9111122223"},      # dup phone
                     ]})
    assert pv.status_code == 200
    items = pv.json()["items"]
    assert any("already exists" in p for p in items[0]["problems"])
    assert any("phone" in p for p in items[1]["problems"])


def test_vendor_preview_writes_nothing(owner):
    pv = client.post("/import/vendors?preview=1", headers=owner["headers"],
                     json={"items": [{"name": "Supplier X", "phone": "7000070000",
                                      "payment_terms_days": 45}]})
    assert pv.status_code == 200, pv.text
    body = pv.json()
    assert body["preview"] is True
    assert body["items"][0]["payment_terms_days"] == 45
    assert _count(Vendor, owner["bid"]) == 0

    commit = client.post("/import/vendors", headers=owner["headers"],
                         json={"items": [{"name": "Supplier X", "phone": "7000070000"}]})
    assert commit.status_code == 200, commit.text
    assert _count(Vendor, owner["bid"]) == 1
