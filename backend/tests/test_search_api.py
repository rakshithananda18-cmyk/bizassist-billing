"""
tests/test_search_api.py
========================
`GET /search` — the one endpoint behind the universal search palette.

Two properties matter more than the feature itself:

  1. TENANT ISOLATION. A search box reaches every table at once, so it is the
     easiest place in the product to leak one business's records to another. An
     integer business id means nothing outside the database that issued it
     (core/identity.py), so the id is resolved here rather than trusted from the
     token.
  2. IT NEVER RAISES. This is called on every keystroke, and `authFetch` toasts
     on any non-2xx (contexts/AuthContext.jsx). A 422 for a half-typed word
     would pop a toast while the owner is still typing.
"""
import os
import sys
import uuid

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_bizassist.db")
os.environ.setdefault("GROQ_API_KEY", "mock_groq_api_key")

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, backend_path)

from fastapi.testclient import TestClient          # noqa: E402
from main_groq import app                          # noqa: E402
from database.db import SessionLocal               # noqa: E402
from database.models import Customer, Vendor, Invoice, Product  # noqa: E402

client = TestClient(app)


def _signup(name="Search Co"):
    uname = f"srch_{uuid.uuid4().hex[:8]}"
    r = client.post("/signup", json={
        "username": uname, "password": "TestPass123!", "business_name": name,
    })
    assert r.status_code == 200, r.text
    b = r.json()
    bid = b["user"]["id"] if isinstance(b.get("user"), dict) else b["id"]
    return bid, {"Authorization": f"Bearer {b['token']}"}


def _seed(bid, tag):
    db = SessionLocal()
    try:
        db.add(Product(business_id=bid, name=f"Widget {tag}", sku=f"SKU{tag}"))
        db.add(Customer(business_id=bid, name=f"Acme {tag}", phone=f"99{tag}"))
        db.add(Vendor(business_id=bid, name=f"Supplier {tag}", phone=f"88{tag}"))
        db.add(Invoice(business_id=bid, invoice_id=f"INV-{tag}",
                       customer=f"Acme {tag}", amount=250.0, status="Pending"))
        db.commit()
    finally:
        db.close()


def _search(headers, q):
    r = client.get(f"/search?q={q}", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["items"]


def test_finds_each_kind_under_the_right_label():
    bid, headers = _signup()
    tag = uuid.uuid4().hex[:6].upper()
    _seed(bid, tag)
    kinds = {i["kind"] for i in _search(headers, tag)}
    assert kinds == {"product", "customer", "vendor", "invoice"}


def test_one_business_never_sees_another(monkeypatch):
    """The property this endpoint most needs. A shared search term must not
    cross the tenant boundary in ANY of the four branches."""
    tag = uuid.uuid4().hex[:6].upper()
    bid_a, headers_a = _signup("Search A")
    _bid_b, headers_b = _signup("Search B")
    _seed(bid_a, tag)

    assert _search(headers_a, tag), "the owner cannot find their own records"
    assert _search(headers_b, tag) == [], "records leaked across businesses"


def test_an_invoice_result_carries_the_number_the_route_needs():
    """`/invoice/:invoiceNo/view` is keyed by the invoice NUMBER, not the row id
    (App.jsx). Sending the id would produce a link that 404s."""
    bid, headers = _signup()
    tag = uuid.uuid4().hex[:6].upper()
    _seed(bid, tag)
    inv = [i for i in _search(headers, tag) if i["kind"] == "invoice"][0]
    assert inv["id"] == f"INV-{tag}"


def test_blank_and_whitespace_queries_return_empty_not_an_error():
    """Called on every keystroke; a non-2xx raises a toast in the client."""
    _bid, headers = _signup()
    for q in ("", "   ", "%20"):
        r = client.get(f"/search?q={q}", headers=headers)
        assert r.status_code == 200, f"q={q!r} returned {r.status_code}"
        assert r.json()["items"] == []


def test_a_wildcard_query_is_not_a_way_to_dump_the_table():
    """`%` is a SQL LIKE wildcard. It must be matched literally rather than
    letting a one-character query enumerate every record."""
    bid, headers = _signup()
    tag = uuid.uuid4().hex[:6].upper()
    _seed(bid, tag)
    items = _search(headers, "%")
    assert all(f"%" in (i["title"] + i["subtitle"]) for i in items) or items == []


def test_results_are_capped_per_kind():
    """The palette is for picking, not browsing — and an uncapped query on a
    10k-invoice business would be sent on every keystroke."""
    bid, headers = _signup()
    tag = uuid.uuid4().hex[:6].upper()
    db = SessionLocal()
    try:
        for n in range(25):
            db.add(Product(business_id=bid, name=f"Bulk {tag} {n}", sku=f"B{tag}{n}"))
        db.commit()
    finally:
        db.close()

    products = [i for i in _search(headers, f"Bulk {tag}") if i["kind"] == "product"]
    assert len(products) <= 10, f"returned {len(products)} — the cap is not applied"

    r = client.get(f"/search?q=Bulk {tag}&limit=999", headers=headers)
    assert len([i for i in r.json()["items"] if i["kind"] == "product"]) <= 10, \
        "the client can raise the cap past the server maximum"


def test_search_requires_authentication():
    assert client.get("/search?q=anything").status_code == 401
