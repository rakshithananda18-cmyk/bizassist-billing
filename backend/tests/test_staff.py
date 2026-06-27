"""
tests/test_staff.py
===================
Multi-user staff sub-accounts. An owner creates cashier logins that SHARE the
owner's business data (via `parent_business_id`); a staff login is scoped to the
owner's business through the JWT `id` claim, so the cashier transparently bills
against the owner's shop while staying role-restricted.
"""
import os
import sys
import uuid

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_bizassist.db")
os.environ.setdefault("GROQ_API_KEY", "mock_groq_api_key")

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, backend_path)

from fastapi.testclient import TestClient
from main_groq import app
from database.db import SessionLocal
from database.models import Product

client = TestClient(app)


def _signup(business_name):
    uname = f"own_{uuid.uuid4().hex[:8]}"
    r = client.post("/signup", json={
        "username": uname, "password": "TestPass123!", "business_name": business_name,
    })
    assert r.status_code == 200, r.text
    b = r.json()
    return {"headers": {"Authorization": f"Bearer {b['token']}"}, "bid": b["id"]}


def _create_staff(owner, username=None, password="CashPass123!", role="cashier"):
    username = username or f"cash_{uuid.uuid4().hex[:8]}"
    r = client.post("/staff", headers=owner["headers"],
                    json={"username": username, "password": password, "role": role})
    return r, username, password


def test_owner_creates_staff_who_shares_business_data():
    owner = _signup("Owner Shop A")
    db = SessionLocal()
    try:
        p = Product(business_id=owner["bid"], name="Shared Widget", selling_price=50, track_inventory=True)
        db.add(p); db.commit()
    finally:
        db.close()

    r, uname, pwd = _create_staff(owner)
    assert r.status_code == 201, r.text
    staff = r.json()
    assert staff["role"] == "cashier"
    assert staff["business_id"] == owner["bid"]

    # Staff logs in → token scoped to the OWNER's business id.
    login = client.post("/login", json={"username": uname, "password": pwd})
    assert login.status_code == 200, login.text
    body = login.json()
    assert body["id"] == owner["bid"]          # data scope == owner's business
    assert body["user_id"] != owner["bid"]     # but their own identity is distinct
    assert body["role"] == "cashier"
    staff_headers = {"Authorization": f"Bearer {body['token']}"}

    # Staff SEES the owner's product (shared data).
    prods = client.get("/products", headers=staff_headers)
    assert prods.status_code == 200
    names = [it["name"] for it in prods.json().get("items", [])]
    assert "Shared Widget" in names


def test_staff_is_cashier_and_role_restricted():
    owner = _signup("Owner Shop B")
    r, uname, pwd = _create_staff(owner)
    assert r.status_code == 201
    body = client.post("/login", json={"username": uname, "password": pwd}).json()
    staff_headers = {"Authorization": f"Bearer {body['token']}"}
    # A cashier cannot view reports nor manage staff.
    assert client.get("/reports/day-summary", headers=staff_headers).status_code == 403
    assert client.get("/staff", headers=staff_headers).status_code == 403
    assert client.post("/staff", headers=staff_headers,
                       json={"username": f"x_{uuid.uuid4().hex[:6]}", "password": "TestPass123!"}).status_code == 403


def test_staff_management_is_tenant_isolated():
    owner_a = _signup("Owner A")
    owner_b = _signup("Owner B")
    ra, _, _ = _create_staff(owner_a)
    staff_a_id = ra.json()["id"]

    # B's staff list never contains A's staff.
    list_b = client.get("/staff", headers=owner_b["headers"]).json()
    assert all(s["id"] != staff_a_id for s in list_b)
    # B cannot delete A's staff…
    assert client.delete(f"/staff/{staff_a_id}", headers=owner_b["headers"]).status_code == 404
    # …but A can.
    assert client.delete(f"/staff/{staff_a_id}", headers=owner_a["headers"]).status_code == 200


def test_staff_validation():
    owner = _signup("Owner V")
    # Weak password → 400.
    assert client.post("/staff", headers=owner["headers"],
                       json={"username": f"weak_{uuid.uuid4().hex[:6]}", "password": "weak"}).status_code == 400
    # Disallowed staff role → 422.
    assert client.post("/staff", headers=owner["headers"],
                       json={"username": f"role_{uuid.uuid4().hex[:6]}", "password": "TestPass123!", "role": "admin"}).status_code == 422
    # Duplicate username → 400.
    r, uname, _ = _create_staff(owner)
    assert r.status_code == 201
    assert client.post("/staff", headers=owner["headers"],
                       json={"username": uname, "password": "TestPass123!"}).status_code == 400


# ── Staff-assigned POS counter prefix (multi-terminal POS §9.3a) ────────────

def test_owner_assigns_staff_counter_prefix_carried_to_login():
    owner = _signup("Owner Counter Shop")
    uname = f"cash_{uuid.uuid4().hex[:8]}"; pwd = "CashPass123!"
    # Create with a messy prefix → normalised to a bare alnum token.
    r = client.post("/staff", headers=owner["headers"],
                    json={"username": uname, "password": pwd, "counter_prefix": " c1- "})
    assert r.status_code == 201, r.text
    assert r.json()["counter_prefix"] == "c1"          # trimmed, de-dashed

    # The assigned prefix is returned on the staff's own login (drives numbering).
    login = client.post("/login", json={"username": uname, "password": pwd})
    assert login.status_code == 200, login.text
    assert login.json()["counter_prefix"] == "c1"

    # Owner can change it later via PATCH.
    sid = r.json()["id"]
    upd = client.patch(f"/staff/{sid}", headers=owner["headers"], json={"counter_prefix": "C2"})
    assert upd.status_code == 200, upd.text
    assert upd.json()["counter_prefix"] == "C2"
    # …and it shows up in the staff list.
    lst = client.get("/staff", headers=owner["headers"]).json()
    assert any(s["id"] == sid and s["counter_prefix"] == "C2" for s in lst)


def test_cashier_cannot_change_their_counter_prefix():
    """A cashier is blocked from /staff entirely, so they can't self-assign a counter."""
    owner = _signup("Owner Lock Shop")
    r, uname, pwd = _create_staff(owner)
    sid = r.json()["id"]
    staff_headers = {"Authorization": f"Bearer {client.post('/login', json={'username': uname, 'password': pwd}).json()['token']}"}
    assert client.patch(f"/staff/{sid}", headers=staff_headers, json={"counter_prefix": "C9"}).status_code == 403
