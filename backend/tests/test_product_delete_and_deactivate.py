"""Removing a product: DELETE and DEACTIVATE answer different questions.

The owner asked for both, and both are correct — but only one of them is safe
once a product has been traded:

  * DEACTIVATE (`PATCH {is_active: false}`) — "stop selling this." The row stays,
    so past invoices still render and reports still foot.
  * DELETE — "this should never have existed": a typo, a duplicate, a bad
    import. Allowed only while the product is genuinely unused.

The refusal is the invariant, not politeness. `invoice_line_items.product_id` is
a real foreign key; orphaning it is exactly what
`scripts/quarantine_fk_orphans.py` had to repair after `PRAGMA foreign_keys` was
found OFF on local installs (18 real orphan rows).

Context for why this landed with the idempotency fix: duplicate products were
being CREATED by an unguarded retry (see test_product_create_idempotency.py) and
then could not be removed, because no delete route existed at all. One cause,
two symptoms.
"""
import os
import sys
import uuid

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_bizassist.db")
os.environ.setdefault("GROQ_API_KEY", "mock_groq_api_key")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fastapi.testclient import TestClient      # noqa: E402
from main_groq import app                      # noqa: E402

client = TestClient(app)


def _signup():
    uname = f"del_{uuid.uuid4().hex[:8]}"
    r = client.post("/signup", json={
        "username": uname, "password": "TestPass123!",
        "business_name": f"Delete Shop {uname}",
    })
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _make_product(headers, name=None):
    name = name or f"Prod {uuid.uuid4().hex[:6]}"
    r = client.post("/products", headers=headers, json={
        "name": name, "unit": "pcs", "selling_price": 50.0, "cost_price": 30.0,
        "cgst_rate": 0, "sgst_rate": 0, "opening_stock": 0, "attributes": {},
    })
    assert r.status_code == 201, r.text
    return r.json()


def _names(headers, **params):
    r = client.get("/products", headers=headers, params=params)
    assert r.status_code == 200, r.text
    body = r.json()
    rows = body if isinstance(body, list) else body.get("products", body.get("items", []))
    return [p["name"] for p in rows]


def test_an_unused_product_can_be_deleted():
    """The duplicate case the owner hit: created by mistake, never traded."""
    h = _signup()
    p = _make_product(h)

    r = client.delete(f"/products/{p['id']}", headers=h)

    assert r.status_code == 200, r.text
    assert r.json()["deleted"] is True
    assert p["name"] not in _names(h)
    # Really gone, not just hidden.
    assert client.get(f"/products/{p['id']}", headers=h).status_code == 404


def test_a_product_with_stock_history_refuses_to_delete_and_says_why():
    """A stock movement is history. Deleting the product would orphan the
    ledger row, which is the defect quarantine_fk_orphans.py cleans up."""
    h = _signup()
    p = _make_product(h)
    adj = client.post(f"/products/{p['id']}/stock/adjustment", headers=h, json={
        "qty_delta": 5, "note": "opening count",
    })
    assert adj.status_code == 201, adj.text

    r = client.delete(f"/products/{p['id']}", headers=h)

    assert r.status_code == 409, r.text
    detail = r.json()["detail"]
    assert "stock movement" in detail, detail
    assert "Deactivate" in detail, "the refusal must name the way forward"
    # Still there, untouched.
    assert client.get(f"/products/{p['id']}", headers=h).status_code == 200


def test_deactivate_is_the_answer_for_a_traded_product():
    """The other half of the pair: it leaves the catalogue without leaving the
    database, so history still resolves."""
    h = _signup()
    p = _make_product(h)
    client.post(f"/products/{p['id']}/stock/adjustment", headers=h,
                json={"qty_delta": 3, "note": "intake"})

    r = client.patch(f"/products/{p['id']}", headers=h, json={"is_active": False})
    assert r.status_code == 200, r.text

    assert p["name"] not in _names(h, is_active=True)
    assert client.get(f"/products/{p['id']}", headers=h).status_code == 200


def test_one_shop_cannot_delete_another_shops_product():
    """Tenant scoping on a destructive route — 404, not 403, so the existence of
    another shop's product is not confirmed either."""
    owner, stranger = _signup(), _signup()
    p = _make_product(owner)

    r = client.delete(f"/products/{p['id']}", headers=stranger)

    assert r.status_code == 404, r.text
    assert client.get(f"/products/{p['id']}", headers=owner).status_code == 200


def test_deleting_a_missing_product_is_a_clean_404():
    h = _signup()
    assert client.delete("/products/99999999", headers=h).status_code == 404
