"""
tests/test_next_invoice_number_preview.py
=========================================
The number the POS SHOWS before a sale is saved.

It used to be derived client-side from the invoice list already in memory, and
that list is fetched with a SEVEN-DAY window (`/billing/invoices?from_date=…`,
pages/Sales.jsx:1015). A counter that had not billed for a week therefore saw an
empty series and displayed `<SERIES>-0001` — observed on business 126, whose
draft tab read `LCL-OW-0001` while `LCL-OW-0001..0003` had existed since
2026-07-03. The SAVED number was always right (the server allocates it); the
number the operator read aloud was not.

Two things have to hold, and the second is the one `peek_number` alone misses:
the preview must see invoices older than any client window, AND it must work
before `document_sequences` has a row for the series — which is the normal state
for every business that has not billed since that table was introduced.
"""
import os
import sys
import uuid

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_bizassist.db")
os.environ.setdefault("GROQ_API_KEY", "mock_groq_api_key")

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, backend_path)

from fastapi.testclient import TestClient           # noqa: E402
from main_groq import app                           # noqa: E402
from database.db import SessionLocal                # noqa: E402
from core.models import DocumentSequence            # noqa: E402
from core.billing import commands as billing        # noqa: E402

client = TestClient(app)


def _account():
    uname = f"nn_{uuid.uuid4().hex[:8]}"
    r = client.post("/signup", json={
        "username": uname, "password": "TestPass123!", "business_name": "Preview Co"})
    assert r.status_code == 200, r.text
    b = r.json()
    tok = b.get("access_token") or b.get("token")
    bid = b["user"]["id"] if isinstance(b.get("user"), dict) else b["id"]
    return bid, {"Authorization": f"Bearer {tok}"}


def test_preview_is_one_past_the_last_invoice_in_the_series():
    bid, headers = _account()
    db = SessionLocal()
    try:
        for n in (1, 2, 3):
            billing.create_sale_invoice(
                db, business_id=bid, place_of_supply="29",
                invoice_no=f"LCL-OW-{n:04d}",
                lines=[{"product_name": "Rice", "quantity": 1, "unit_price": 10}])
    finally:
        db.close()

    r = client.get("/sales/next-number?counter_prefix=LCL-OW", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["next"] == "LCL-OW-0004"
    assert r.json()["last"] == 3


def test_preview_works_with_no_document_sequences_row():
    """The state every pre-existing business is in.

    `peek_number` reads document_sequences and would answer 0001 here. The
    endpoint has to fall back to scanning the series, exactly as `next_number`
    does when it seeds a brand-new counter.
    """
    bid, headers = _account()
    db = SessionLocal()
    try:
        billing.create_sale_invoice(
            db, business_id=bid, place_of_supply="29", invoice_no="LCL-OW-0009",
            lines=[{"product_name": "Rice", "quantity": 1, "unit_price": 10}])
        db.query(DocumentSequence).filter(
            DocumentSequence.business_id == bid).delete()
        db.commit()
        assert db.query(DocumentSequence).filter(
            DocumentSequence.business_id == bid).count() == 0
    finally:
        db.close()

    r = client.get("/sales/next-number?counter_prefix=LCL-OW", headers=headers)
    assert r.json()["next"] == "LCL-OW-0010", "fell back to 0001 — the empty-table bug"


def test_series_do_not_bleed_into_each_other():
    """`LCL-OW` and `OW` are deliberately separate series (sequence.suffix_of).
    A preview that mixed them would hand one counter another's numbers."""
    bid, headers = _account()
    db = SessionLocal()
    try:
        for no in ("OW-0007", "LCL-OW-0002"):
            billing.create_sale_invoice(
                db, business_id=bid, place_of_supply="29", invoice_no=no,
                lines=[{"product_name": "Rice", "quantity": 1, "unit_price": 10}])
    finally:
        db.close()

    assert client.get("/sales/next-number?counter_prefix=OW",
                      headers=headers).json()["next"] == "OW-0008"
    assert client.get("/sales/next-number?counter_prefix=LCL-OW",
                      headers=headers).json()["next"] == "LCL-OW-0003"


def test_the_route_is_not_swallowed_by_the_invoice_lookup():
    """`/sales/{invoice_no}` is declared in the same router. If it came first,
    FastAPI would match `next-number` as an invoice number and 404."""
    _, headers = _account()
    r = client.get("/sales/next-number?counter_prefix=OW", headers=headers)
    assert r.status_code == 200, f"shadowed by /sales/{{invoice_no}}: {r.text}"
    assert "not found" not in r.text.lower()


def test_a_brand_new_counter_starts_at_one():
    _, headers = _account()
    r = client.get("/sales/next-number?counter_prefix=C7", headers=headers)
    assert r.json()["next"] == "C7-0001"
    assert r.json()["last"] == 0
