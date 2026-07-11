"""
tests/test_import_preview_and_shift_invoices.py
===============================================
Owner-requirement batch (2026-07):
  * Products import approval flow: ?preview=1 parses WITHOUT writing; the
    JSON commit path still writes; duplicate names/SKUs are flagged.
  * GET /shifts/{id}/invoices: per-shift invoice drill-down (visibility rules).
"""
import io
import os

os.environ["DATABASE_URL"] = "sqlite:///./test_bizassist.db"
os.environ["GROQ_API_KEY"] = "mock_groq_api_key"

import sys
backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, backend_path)

import pytest
from fastapi.testclient import TestClient
from main_groq import app

client = TestClient(app)

OWNER = {"username": "own_импorт_owner".replace("импorт", "import"), "password": "Password123",
         "business_name": "Import Preview Store"}


@pytest.fixture(autouse=True)
def clear_windows():
    from services.rate_limiter import _ip_window, _upload_window
    _ip_window.clear()
    _upload_window.clear()


def _signup_or_login(creds):
    r = client.post("/signup", json=creds)
    if r.status_code != 200:
        r = client.post("/login", json={"username": creds["username"], "password": creds["password"]})
    assert r.status_code == 200, r.text
    return r.json()


def _headers(tok):
    return {"Authorization": f"Bearer {tok}"}


def _product_count(headers):
    r = client.get("/products?per_page=1000", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    return len(body.get("items", body if isinstance(body, list) else []))


def test_import_preview_writes_nothing_then_commit_writes():
    owner = _signup_or_login(OWNER)
    h = _headers(owner["token"])
    before = _product_count(h)

    csv_bytes = (
        "name,sku,selling_price,cost_price,opening_stock\n"
        "Preview Widget A,PW-A,100,60,5\n"
        "Preview Widget B,PW-B,200,120,3\n"
    ).encode()

    # 1. Preview: parsed rows come back, NOTHING lands in the catalog.
    # (The frontend calls /billing/import/... — its authFetch strips the
    #  /billing prefix; the raw backend path is /import/products.)
    r = client.post("/import/products?preview=1", headers=h,
                    files={"file": ("products.csv", io.BytesIO(csv_bytes), "text/csv")})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["preview"] is True and body["count"] == 2
    assert body["items"][0]["name"] == "Preview Widget A"
    assert body["items"][0]["problems"] == []
    assert _product_count(h) == before, "preview must not create products"

    # 2. Commit the approved (possibly edited) rows as JSON.
    rows = [{k: v for k, v in it.items() if k not in ("problems", "row")} for it in body["items"]]
    r = client.post("/import/products", headers=h, json={"items": rows})
    assert r.status_code == 200, r.text
    assert _product_count(h) == before + 2

    # 3. A second preview flags the duplicates it would create.
    r = client.post("/import/products?preview=1", headers=h,
                    files={"file": ("products.csv", io.BytesIO(csv_bytes), "text/csv")})
    assert r.status_code == 200
    probs = [p for it in r.json()["items"] for p in it["problems"]]
    assert any("already exists" in p for p in probs)


def test_shift_invoices_endpoint_visibility():
    owner = _signup_or_login(OWNER)
    h = _headers(owner["token"])

    # Nonexistent shift → 404 (scoped to the business).
    r = client.get("/shifts/999999/invoices", headers=h)
    assert r.status_code == 404

    # Open a shift → empty invoice list with a total of 0.
    r = client.post("/shifts/open", json={"opening_cash": 500}, headers=h)
    if r.status_code == 409:   # already open from a previous test run
        r = client.get("/shifts/current", headers=h)
        shift_id = r.json()["shift"]["id"]
    else:
        assert r.status_code == 201, r.text
        shift_id = r.json()["shift"]["id"]

    r = client.get(f"/shifts/{shift_id}/invoices", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["shift_id"] == shift_id
    assert isinstance(body["invoices"], list)
    assert body["total_collected"] == pytest.approx(sum(i["collected_in_shift"] for i in body["invoices"]))
