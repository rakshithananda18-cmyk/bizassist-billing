"""
tests/test_notifications.py
===========================
`GET /alerts/notifications` — what the business needs told, right now.

The scheduled jobs in services/alert_jobs.py already computed all of this and
handed it to notifier.notify(), which discards it when SMTP is unconfigured (the
default). So the findings existed and were unreachable. This endpoint reads the
same rows; these tests pin the boundaries that decide whether an owner is warned
or not.

Run:
    cd backend && python -m pytest tests/test_notifications.py -v
"""
import os
import sys
import uuid
from datetime import timedelta

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_bizassist.db")
os.environ.setdefault("GROQ_API_KEY", "mock_groq_api_key")

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, backend_path)

from fastapi.testclient import TestClient          # noqa: E402
from main_groq import app                          # noqa: E402
from database.db import SessionLocal               # noqa: E402
from database.models import Inventory, AlertConfig, Product  # noqa: E402
from core.models import StockLedger                 # noqa: E402
from services.dates import biz_now                  # noqa: E402

client = TestClient(app)


def _signup(name="Notify Co"):
    uname = f"ntf_{uuid.uuid4().hex[:8]}"
    r = client.post("/signup", json={
        "username": uname, "password": "TestPass123!", "business_name": name,
    })
    assert r.status_code == 200, r.text
    b = r.json()
    bid = b["user"]["id"] if isinstance(b.get("user"), dict) else b["id"]
    return bid, {"Authorization": f"Bearer {b['token']}"}


def _batch(bid, name, qty, expiry=None):
    """One INVENTORY row — a batch. Expiry lives per batch, so the expiry
    checks are built from these."""
    db = SessionLocal()
    try:
        db.add(Inventory(business_id=bid, product_name=name, stock=qty,
                         expiry_date=expiry))
        db.commit()
    finally:
        db.close()


def _product(bid, name, qty, min_stock=None, movements=None):
    """A catalogue product whose stock comes from the LEDGER, which is what the
    dashboard and the bell both read. `movements` writes several ledger rows so
    a multi-batch product can be built — the case where per-batch counting and
    per-product counting disagree."""
    db = SessionLocal()
    try:
        import json
        p = Product(business_id=bid, name=name, track_inventory=True,
                    attributes=json.dumps({"min_stock": min_stock}) if min_stock is not None else None)
        db.add(p)
        db.commit()
        db.refresh(p)
        for delta in (movements if movements is not None else [qty]):
            db.add(StockLedger(business_id=bid, product_id=p.id, product_name=name,
                               movement_type="opening", qty_delta=delta))
        db.commit()
        return p.id
    finally:
        db.close()


def _kinds(headers):
    r = client.get("/alerts/notifications", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    return {i["kind"]: i for i in body["items"]}, body


def test_a_healthy_business_has_nothing_to_say():
    _bid, headers = _signup()
    kinds, body = _kinds(headers)
    assert kinds == {}
    assert body["count"] == 0
    # No items means no colour — the bell must not light up over nothing.
    assert body["severity"] is None


def test_low_stock_is_reported_against_the_threshold():
    bid, headers = _signup()
    _product(bid, "Below", 3)        # under the default threshold of 10
    _product(bid, "Plenty", 500)
    kinds, _ = _kinds(headers)
    assert kinds["low_stock"]["count"] == 1, "the healthy product must not be counted"
    assert "Below" in kinds["low_stock"]["detail"]


def test_an_emptied_batch_is_not_a_stockout():
    """The bug this endpoint shipped with, seen live: the bell said "6 products
    low, 3 out of stock" while the dashboard said "All stock levels are safe",
    both on screen at once. The bell was counting INVENTORY rows — one per batch
    — so a well-stocked product with three sold-through batches read as three
    stockouts. The dashboard was right. Stock is per product, summed from the
    ledger."""
    bid, headers = _signup()
    # 200 units delivered across four batches; three have since sold out.
    _product(bid, "Sugar 50kg", None, movements=[50, 50, 50, 50, -50, -50, -50])
    kinds, _ = _kinds(headers)
    assert "low_stock" not in kinds, "50 units in hand is not a stockout"


def test_out_of_stock_outranks_merely_low():
    """Both are 'low stock', but one cannot be sold at all. Severity has to
    separate them or the bell shows amber while the shelf is empty."""
    bid, headers = _signup()
    _product(bid, "Low", 4)
    kinds, body = _kinds(headers)
    assert kinds["low_stock"]["severity"] == "warning"

    _product(bid, "Gone", 0)
    kinds, body = _kinds(headers)
    assert kinds["low_stock"]["severity"] == "danger"
    assert body["severity"] == "danger", "the most urgent item sets the summary"


def test_a_products_own_minimum_beats_the_global_threshold():
    """A merchant who set a per-product minimum is not second-guessed — same
    field the dashboard reads (`attributes.min_stock`)."""
    bid, headers = _signup()
    # 4 units, but this product is fine at 2 — below the global 10, above its own.
    _product(bid, "Slow mover", 4, min_stock=2)
    assert "low_stock" not in _kinds(headers)[0]

    _product(bid, "Fast mover", 4, min_stock=20)
    assert _kinds(headers)[0]["low_stock"]["count"] == 1


def test_services_are_not_stock():
    """`track_inventory=False` is how a service or prepared food is modelled.
    It has no stock to be low on."""
    bid, headers = _signup()
    db = SessionLocal()
    try:
        db.add(Product(business_id=bid, name="Haircut", track_inventory=False))
        db.commit()
    finally:
        db.close()
    assert "low_stock" not in _kinds(headers)[0]


def test_expired_stock_is_reported_separately_from_expiring():
    """The email job only ever looked at `0 <= days_left <= threshold`, so a
    batch that had ALREADY gone off fell out of the window and was never
    mentioned — the one state where the owner most needs telling."""
    bid, headers = _signup()
    today = biz_now().date()
    _batch(bid, "Gone off", 5, (today - timedelta(days=3)).isoformat())
    _batch(bid, "Going off", 5, (today + timedelta(days=7)).isoformat())
    _batch(bid, "Fine", 5, (today + timedelta(days=900)).isoformat())

    kinds, _ = _kinds(headers)
    assert kinds["expired"]["count"] == 1
    assert kinds["expired"]["severity"] == "danger"
    assert kinds["expiring"]["count"] == 1, "the far-future batch is not expiring soon"
    assert "Going off" in kinds["expiring"]["detail"]


def test_an_empty_batch_cannot_expire():
    """Expiry only matters for stock that is still on the shelf. Counting sold-out
    batches would make the warning permanent and therefore ignorable."""
    bid, headers = _signup()
    today = biz_now().date()
    _batch(bid, "Sold out long ago", 0, (today - timedelta(days=30)).isoformat())
    kinds, _ = _kinds(headers)
    assert "expired" not in kinds


def test_turning_alerts_off_silences_the_bell_too():
    """`active=False` is an explicit 'stop telling me'. The bell is not a
    separate channel that gets to ignore the switch."""
    bid, headers = _signup()
    _product(bid, "Below", 1)
    assert "low_stock" in _kinds(headers)[0]

    db = SessionLocal()
    try:
        db.add(AlertConfig(business_id=bid, active=False))
        db.commit()
    finally:
        db.close()
    assert _kinds(headers)[0] == {}


def test_a_configured_threshold_is_honoured():
    bid, headers = _signup()
    _product(bid, "Twenty", 20)
    assert "low_stock" not in _kinds(headers)[0], "20 is above the default of 10"

    db = SessionLocal()
    try:
        db.add(AlertConfig(business_id=bid, active=True, low_stock_threshold=50,
                           alert_low_stock=True, alert_overdue=True, alert_expiry=True))
        db.commit()
    finally:
        db.close()
    assert _kinds(headers)[0]["low_stock"]["count"] == 1


def test_one_business_never_sees_another():
    bid_a, headers_a = _signup("Notify A")
    _bid_b, headers_b = _signup("Notify B")
    _product(bid_a, "A's problem", 1)
    assert "low_stock" in _kinds(headers_a)[0]
    assert _kinds(headers_b)[0] == {}, "stock scoping leaked across businesses"


def test_the_email_alert_counts_the_same_products_as_the_app(monkeypatch):
    """Three surfaces, one number.

    The scheduled email ran its own `inventory.stock <= threshold` query, so a
    product across four batches with three sold through was three separate
    low-stock lines in the owner's inbox while the dashboard said none. It reads
    the shared definition now; this pins that it does, by firing the real job and
    reading what it would have sent.
    """
    import services.alert_jobs as jobs

    bid, headers = _signup()
    email = f"{uuid.uuid4().hex[:8]}@example.test"
    db = SessionLocal()
    try:
        db.add(AlertConfig(business_id=bid, active=True, email=email,
                           alert_low_stock=True, low_stock_threshold=10))
        db.commit()
    finally:
        db.close()

    # 50 units in hand, spread over four batches with three emptied.
    _product(bid, "Sugar 50kg", None, movements=[50, 50, 50, 50, -50, -50, -50])
    _product(bid, "Actually low", 2)

    sent = []
    monkeypatch.setattr(jobs, "notify",
                        lambda to, wa, subject, body: sent.append((to, subject, body)))
    jobs.run_low_stock_alerts()

    mine = [s for s in sent if s[0] == email]
    assert len(mine) == 1, "the job must email this business exactly once"
    _to, subject, body = mine[0]
    assert "1 Product" in subject, f"expected only the genuinely low product: {subject}"
    assert "Actually low" in body
    assert "Sugar 50kg" not in body, "a sold-through batch is not a low product"

    # …and the bell agrees, because both call low_stock_products().
    assert _kinds(headers)[0]["low_stock"]["count"] == 1


def test_cashiers_are_refused():
    """Overdue totals are financial. The endpoint sits behind the same guard as
    the rest of the alerts module."""
    _bid, headers = _signup()
    r = client.get("/alerts/notifications", headers=headers)
    assert r.status_code == 200          # owner is fine
    r = client.get("/alerts/notifications")
    assert r.status_code == 401          # and it is not public
