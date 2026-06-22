"""
tests/test_sync_pull.py
=======================
R7b Slice 2 — offline delta PULL (`GET /sync/pull`).

The client learns "what changed since my cursor" over the append-only money
entities, exactly once and gap-free, via a per-entity autoincrement-id cursor.

Covers: full backfill from an empty cursor, re-pull with the returned cursor is
empty (no re-delivery), a new sale appears ONLY past the cursor, `has_more`
paging, and tenant isolation (business B never sees business A's rows, and the
numeric cursors are per-tenant).

Self-contained signups + product; order-independent.
"""
import os
import sys
import json
import uuid

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_bizassist.db")
os.environ.setdefault("GROQ_API_KEY", "mock_groq_api_key")

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, backend_path)

import pytest
from fastapi.testclient import TestClient
from main_groq import app
from database.db import SessionLocal
from database.models import Product, Inventory, User

client = TestClient(app)


@pytest.fixture(autouse=True)
def _clear_rate_limit():
    from services.rate_limiter import _ip_window, _upload_window
    _ip_window.clear()
    _upload_window.clear()


def _signup(name="Pull Biz"):
    uname = f"pull_{uuid.uuid4().hex[:8]}"
    r = client.post("/signup", json={"username": uname, "password": "TestPass123!", "business_name": name})
    assert r.status_code == 200, r.text
    b = r.json()
    bid = b["id"]
    db = SessionLocal()
    try:
        u = db.query(User).filter(User.id == bid).first()
        u.state_code = "29"
        p = Product(business_id=bid, name="Pull Rice", sku=f"PR{uuid.uuid4().hex[:5]}",
                    unit="Bag", hsn_sac="1006", cgst_rate=9, sgst_rate=9, igst_rate=18,
                    selling_price=100, track_inventory=True)
        db.add(p); db.flush()
        db.add(Inventory(business_id=bid, product_name="Pull Rice", product_id=p.id, stock=500))
        db.commit()
        pid = p.id
    finally:
        db.close()
    return {"headers": {"Authorization": f"Bearer {b['token']}"}, "bid": bid, "pid": pid}


def _sale(a, qty=1):
    r = client.post("/sales", headers=a["headers"],
                    json={"place_of_supply": "29", "lines": [{"product_id": a["pid"], "quantity": qty, "unit_price": 100}]})
    assert r.status_code == 200, r.text
    return r.json()


def _pull(a, cursor=None, limit=None):
    params = {}
    if cursor is not None:
        params["since"] = json.dumps(cursor)
    if limit is not None:
        params["limit"] = limit
    r = client.get("/sync/pull", headers=a["headers"], params=params)
    assert r.status_code == 200, r.text
    return r.json()


def test_backfill_then_empty_repull():
    a = _signup()
    inv = _sale(a)                      # one invoice + its stock movement
    body = _pull(a)                     # empty cursor → full backfill
    ids = [r["id"] for r in body["changes"]["invoice"]]
    assert inv["id"] in ids
    assert len(body["changes"]["stock"]) >= 1
    assert body["has_more"] is False

    # Re-pull with the returned cursor → nothing new, cursor unchanged.
    body2 = _pull(a, cursor=body["cursor"])
    assert body2["changes"]["invoice"] == []
    assert body2["changes"]["stock"] == []
    assert body2["cursor"]["invoice"] == body["cursor"]["invoice"]


def test_only_new_rows_past_cursor():
    a = _signup()
    _sale(a)
    first = _pull(a)
    cur = first["cursor"]

    inv2 = _sale(a)                     # a second sale AFTER the cursor
    delta = _pull(a, cursor=cur)
    inv_ids = [r["id"] for r in delta["changes"]["invoice"]]
    assert inv_ids == [inv2["id"]]      # only the new one, exactly once


def test_has_more_paging():
    a = _signup()
    _sale(a); _sale(a); _sale(a)        # 3 invoices
    page = _pull(a, cursor={"invoice": 0}, limit=1)
    assert len(page["changes"]["invoice"]) == 1
    assert page["has_more"] is True
    # Drain using the advancing cursor until caught up.
    seen = list(page["changes"]["invoice"])
    cur = page["cursor"]
    for _ in range(10):
        if not page["has_more"]:
            break
        page = _pull(a, cursor=cur, limit=1)
        seen += page["changes"]["invoice"]
        cur = page["cursor"]
    assert len([r["id"] for r in seen]) >= 3


def test_pull_is_tenant_scoped():
    a, b = _signup(name="Pull A"), _signup(name="Pull B")
    inv_a = _sale(a)
    body_b = _pull(b)                   # B pulls from scratch
    a_ids = [r["id"] for r in body_b["changes"]["invoice"]]
    assert inv_a["id"] not in a_ids
    assert body_b["changes"]["invoice"] == []   # B has made no sales


def test_bad_cursor_is_safe_backfill():
    a = _signup()
    _sale(a)
    r = client.get("/sync/pull", headers=a["headers"], params={"since": "not-json"})
    assert r.status_code == 200
    assert len(r.json()["changes"]["invoice"]) >= 1   # garbage cursor → full backfill, no crash
