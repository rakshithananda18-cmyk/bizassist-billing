"""Creating a product twice with the same client key must create ONE product.

THE REPORTED SYMPTOM was "the save is saving multiple times" on the stock-in
pages. The cause was that a two-step operation had a guard on only ONE step:

    StockIntakeSheet saves a NEW row by calling
        POST /billing/products                  <- no idempotency guard
        POST /billing/products/{id}/stock/adjustment   <- ReplayGuard since day 1

so a double-click, a flaky connection or an offline replay produced a SECOND
product with the same name, while the stock movement was correctly deduplicated.
Nothing downstream caught it either: `products` has no unique constraint on
(business_id, name) — `services/sync_worker` matches products BY NAME on pull
precisely because none exists.

It compounded, which is why the owner met it as two separate complaints: there
is no DELETE route for products, so the duplicates could not be removed.
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
    uname = f"idem_{uuid.uuid4().hex[:8]}"
    r = client.post("/signup", json={
        "username": uname, "password": "TestPass123!",
        "business_name": f"Idem Shop {uname}",
    })
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _payload(name):
    return {
        "name": name, "unit": "pcs", "selling_price": 100.0, "cost_price": 60.0,
        "cgst_rate": 0, "sgst_rate": 0, "opening_stock": 0, "attributes": {},
    }


def _catalogue(headers, name):
    r = client.get("/products", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    rows = body if isinstance(body, list) else body.get("products", body.get("items", []))
    return [p for p in rows if p.get("name") == name]


def test_the_same_client_key_creates_one_product_not_two():
    """RED ON REVERT: without the ReplayGuard this creates two products."""
    headers = _signup()
    name = f"Wheat Flour {uuid.uuid4().hex[:6]}"
    key = str(uuid.uuid4())
    hdrs = {**headers, "X-Client-Request-Id": key}

    first = client.post("/products", headers=hdrs, json=_payload(name))
    assert first.status_code == 201, first.text

    second = client.post("/products", headers=hdrs, json=_payload(name))
    assert second.status_code in (200, 201), second.text

    # Same row echoed back, not a new one.
    assert second.json().get("id") == first.json().get("id")
    assert len(_catalogue(headers, name)) == 1, (
        "the retry created a SECOND product — this is the duplicate the owner "
        "reported as 'save is saving multiple times'"
    )


def test_a_different_key_still_creates_a_second_product():
    """The guard must not become 'never create the same name twice'. Two
    genuinely separate intents are the shop's business, not ours — a counter may
    legitimately hold two products with the same name and different batches."""
    headers = _signup()
    name = f"Sugar {uuid.uuid4().hex[:6]}"

    a = client.post("/products",
                    headers={**headers, "X-Client-Request-Id": str(uuid.uuid4())},
                    json=_payload(name))
    b = client.post("/products",
                    headers={**headers, "X-Client-Request-Id": str(uuid.uuid4())},
                    json=_payload(name))

    assert a.status_code == 201 and b.status_code == 201
    assert a.json()["id"] != b.json()["id"]
    assert len(_catalogue(headers, name)) == 2


def test_no_key_behaves_exactly_as_before():
    """The header is optional. An older client that does not send it must keep
    working — `ReplayGuard.active` is False and the route runs normally."""
    headers = _signup()
    name = f"Rice {uuid.uuid4().hex[:6]}"

    r = client.post("/products", headers=headers, json=_payload(name))

    assert r.status_code == 201, r.text
    assert len(_catalogue(headers, name)) == 1


def test_one_business_key_cannot_replay_into_another():
    """The wall is tenant-scoped. Two shops that happen to mint the same id must
    not see each other's response — that would be a cross-tenant read."""
    shop_a, shop_b = _signup(), _signup()
    shared_key = str(uuid.uuid4())
    name_a = f"Salt A {uuid.uuid4().hex[:6]}"
    name_b = f"Salt B {uuid.uuid4().hex[:6]}"

    ra = client.post("/products",
                     headers={**shop_a, "X-Client-Request-Id": shared_key},
                     json=_payload(name_a))
    rb = client.post("/products",
                     headers={**shop_b, "X-Client-Request-Id": shared_key},
                     json=_payload(name_b))

    assert ra.status_code == 201 and rb.status_code == 201
    assert rb.json()["name"] == name_b, "shop B was served shop A's stored response"
    assert len(_catalogue(shop_b, name_b)) == 1
    assert len(_catalogue(shop_b, name_a)) == 0
