"""
tests/test_parity_is_bidirectional.py — parity asked only half the question
============================================================================

`_cloud_parity_check` is the safety net for the two databases drifting apart. It
iterated `local_child[table]` — LOCAL rows — and asked, for each, whether the
cloud had it and had it on the right invoice. Three findings came out of that:
WRONG_INVOICE, MISSING (from the cloud), PAID_STATE.

Every one of them is the same direction: **what is the cloud missing?**

The other direction has no representation at all, and it is the one that costs
money. A row created ON THE CLOUD that never reaches this device is invisible to
parity, because parity never enumerates cloud rows looking for local absence.

WHAT THAT MISSED — LCL-OW-0037
------------------------------
    30 Jul 11:43 UTC   ₹124 settled on the cloud against cloud invoice 835.
    30 Jul 11:43:26    the pull starts timing out (10s HTTP timeout then) and
                       does not succeed again for over a day.
    31 Jul 18:58       the local invoice still reads Pending / ₹0, so it is
                       settled AGAIN by cheque and pushed.
    →                  the cloud holds ₹248 against a ₹124 invoice.

Parity ran throughout and logged "cloud parity OK — no drift detected", twice
over:

  1. it never enumerated the cloud's payments looking for local absence; and
  2. its paid-state check compares the cloud's STORED paid_amount against the
     cloud's OWN payment sum — two numbers that agree perfectly when the same
     invoice has been settled twice. `total_amount` was read into a local
     variable on the line above and never referenced again.

THE TESTS
---------
These drive the real `_cloud_parity_check` against a real sqlite database with
the cloud HTTP call stubbed, because the behaviour under test is what the
function CONCLUDES from a snapshot — not how it fetches one.
"""
import json
import os
import sys

os.environ.setdefault("JWT_SECRET",   "test-secret-for-parity-bidi-abcdef123")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_bizassist.db")
os.environ.setdefault("GROQ_API_KEY", "mock_groq_api_key")
os.environ.setdefault("CLOUD_API_URL", "http://127.0.0.1:9")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest

from database.db import SessionLocal
from database.models import (
    Base, Invoice, InvoicePayment, SyncInbox, SyncQueue, User,
)
from services import sync_worker as SW
from services.dates import utc_now

BID = 90410
INV_UID = "inv-uid-0037"
LOCAL_PAY_UID = "pay-uid-cheque"
CLOUD_ONLY_PAY_UID = "pay-uid-bank"


class _FakeResponse:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


@pytest.fixture(scope="module", autouse=True)
def ensure_schema():
    db = SessionLocal()
    try:
        Base.metadata.create_all(bind=db.get_bind())
    finally:
        db.close()


@pytest.fixture
def db():
    s = SessionLocal()
    _clean(s)
    # An owner row, one invoice of ₹124, and ONE local payment of ₹124.
    s.add(User(id=BID, username=f"parity_owner_{BID}", email=f"p{BID}@t.invalid",
               password="x", public_id=f"BA-PAR{BID}", business_name="Parity Co"))
    s.flush()
    inv = Invoice(business_id=BID, invoice_id="LCL-OW-0037", uid=INV_UID,
                  amount=124.0, total_amount=124.0, paid_amount=124.0,
                  status="Paid", customer="Rakshith Mom",
                  created_at=utc_now(), updated_at=utc_now())
    s.add(inv)
    s.flush()
    s.add(InvoicePayment(business_id=BID, invoice_id=inv.id, uid=LOCAL_PAY_UID,
                         amount_paid=124.0, payment_mode="Cheque",
                         note="Settlement (FIFO)",
                         created_at=utc_now(), updated_at=utc_now()))
    s.commit()
    s.invoice_row_id = inv.id
    try:
        yield s
    finally:
        s.rollback()
        _clean(s)
        s.close()


def _clean(s):
    ids = [r[0] for r in s.query(Invoice.id).filter(Invoice.business_id == BID).all()]
    if ids:
        s.query(InvoicePayment).filter(InvoicePayment.invoice_id.in_(ids)).delete(
            synchronize_session=False)
    s.query(Invoice).filter(Invoice.business_id == BID).delete()
    s.query(SyncInbox).filter(SyncInbox.business_id == BID).delete()
    s.query(SyncQueue).filter(SyncQueue.business_id == BID).delete()
    s.query(User).filter(User.id == BID).delete()
    s.commit()


def _run_parity(db, monkeypatch, changes):
    """Drive the real sweep against a fixed cloud snapshot."""
    monkeypatch.setattr(SW, "_get_cloud_token", lambda _bid: "fake-token")
    monkeypatch.setattr(SW.httpx, "get",
                        lambda *a, **k: _FakeResponse({"changes": changes}))
    SW._LAST_PARITY.pop(BID, None)      # bypass the 6-hour rate limit
    return SW._cloud_parity_check(db, BID)


def _cloud_snapshot(payments, *, paid_amount, total_amount=124.0):
    return {
        "invoices": [{
            "id": 835, "uid": INV_UID, "invoice_id": "LCL-OW-0037",
            "paid_amount": paid_amount, "total_amount": total_amount,
        }],
        "invoice_payments": payments,
        "invoice_line_items": [],
    }


# ═════════════════════════════════════════════════════════════════════════════
# 1. A row the cloud has and we do not
# ═════════════════════════════════════════════════════════════════════════════

class TestCloudOnlyRowsAreFound:

    def test_a_payment_only_on_the_cloud_is_reported(self, db, monkeypatch):
        """THE GATE. Before this, the sweep logged 'cloud parity OK'."""
        summary = _run_parity(db, monkeypatch, _cloud_snapshot([
            {"id": 71, "uid": LOCAL_PAY_UID, "invoice_id": 835,
             "amount_paid": 124.0, "payment_mode": "Cheque"},
            {"id": 70, "uid": CLOUD_ONLY_PAY_UID, "invoice_id": 835,
             "amount_paid": 124.0, "payment_mode": "Bank"},
        ], paid_amount=248.0))

        assert summary["cloud_only"] == 1, (
            "the Bank payment exists on the cloud and not here — parity must say so"
        )

    def test_it_is_handed_to_the_inbox_with_its_payload(self, db, monkeypatch):
        """Noticing is not enough; the row has to have somewhere to go.

        The pull cursor is long past this row's `updated_at`, so no ordinary
        cycle will re-offer it. The inbox is the only route back, and it applies
        through `_apply_pulled_row` — the same single apply path — rather than a
        second INSERT written here.
        """
        _run_parity(db, monkeypatch, _cloud_snapshot([
            {"id": 70, "uid": CLOUD_ONLY_PAY_UID, "invoice_id": 835,
             "amount_paid": 124.0, "payment_mode": "Bank",
             "note": "Settlement (FIFO)"},
        ], paid_amount=248.0))

        held = (db.query(SyncInbox)
                .filter(SyncInbox.business_id == BID,
                        SyncInbox.uid == CLOUD_ONLY_PAY_UID)
                .one())
        assert held.reason == "cloud-only"
        assert held.entity == "invoice_payments"
        assert held.applied_at is None
        # Without the payload there is nothing to re-apply.
        assert json.loads(held.payload)["amount_paid"] == 124.0

    def test_a_row_present_on_both_sides_is_not_reported(self, db, monkeypatch):
        """Counter-test: the check must not flag agreement as drift.

        A sweep that reports every row is as useless as one that reports none,
        and it would fill the inbox with rows that are already here.
        """
        summary = _run_parity(db, monkeypatch, _cloud_snapshot([
            {"id": 71, "uid": LOCAL_PAY_UID, "invoice_id": 835,
             "amount_paid": 124.0, "payment_mode": "Cheque"},
        ], paid_amount=124.0))

        assert summary["cloud_only"] == 0
        assert db.query(SyncInbox).filter(SyncInbox.business_id == BID).count() == 0


# ═════════════════════════════════════════════════════════════════════════════
# 2. Payments summing to more than the invoice
# ═════════════════════════════════════════════════════════════════════════════

class TestOverPaymentIsFlagged:

    def test_two_settlements_of_a_single_invoice_are_reported(self, db, monkeypatch):
        """Both cloud numbers agree with each other and neither is right.

        stored_paid 248.00 == actual_paid 248.00, so the paid-state check passes.
        The invoice is for 124.00.
        """
        summary = _run_parity(db, monkeypatch, _cloud_snapshot([
            {"id": 71, "uid": LOCAL_PAY_UID, "invoice_id": 835,
             "amount_paid": 124.0, "payment_mode": "Cheque"},
            {"id": 70, "uid": CLOUD_ONLY_PAY_UID, "invoice_id": 835,
             "amount_paid": 124.0, "payment_mode": "Bank"},
        ], paid_amount=248.0, total_amount=124.0))

        assert summary["over_paid"] == 1
        assert summary["paid_state"] == 0, (
            "stored and actual agree, so the old check has nothing to say — "
            "which is exactly why the over-payment check has to exist separately"
        )

    def test_an_exactly_settled_invoice_is_not_flagged(self, db, monkeypatch):
        summary = _run_parity(db, monkeypatch, _cloud_snapshot([
            {"id": 71, "uid": LOCAL_PAY_UID, "invoice_id": 835,
             "amount_paid": 124.0, "payment_mode": "Cheque"},
        ], paid_amount=124.0, total_amount=124.0))
        assert summary["over_paid"] == 0

    def test_rounding_does_not_trip_it(self, db, monkeypatch):
        """A cent over is arithmetic, not a double payment.

        The 0.05 tolerance mirrors the stored-vs-actual check directly above it;
        without it every rounded invoice in the book would be reported.
        """
        summary = _run_parity(db, monkeypatch, _cloud_snapshot([
            {"id": 71, "uid": LOCAL_PAY_UID, "invoice_id": 835,
             "amount_paid": 124.02, "payment_mode": "Cheque"},
        ], paid_amount=124.02, total_amount=124.0))
        assert summary["over_paid"] == 0


# ═════════════════════════════════════════════════════════════════════════════
# 3. "Parity OK" has to mean parity is OK
# ═════════════════════════════════════════════════════════════════════════════

class TestTheSummaryCountsTheNewFindings:

    def test_the_clean_path_still_reports_clean(self, db, monkeypatch):
        summary = _run_parity(db, monkeypatch, _cloud_snapshot([
            {"id": 71, "uid": LOCAL_PAY_UID, "invoice_id": 835,
             "amount_paid": 124.0, "payment_mode": "Cheque"},
        ], paid_amount=124.0))
        assert (summary["missing"] + summary["wrong_invoice"]
                + summary["paid_state"] + summary["cloud_only"]
                + summary["over_paid"]) == 0

    def test_parity_sends_query_params_the_endpoint_actually_reads(self, db, monkeypatch):
        """A query parameter the endpoint does not declare is silently dropped.

        For the lifetime of this function parity sent:

            params={"since": "2020-01-01T00:00:00"}

        `/api/sync/pull` takes `last_sync_at`, not `since`. FastAPI drops unknown
        query params without complaint, so `last_sync_at` arrived as None, the
        endpoint fell through to `datetime(1970, 1, 1)`, and that "2020" never
        did anything. The behaviour happened to be what parity wanted — a full
        snapshot — which is exactly why nobody noticed for months, and why the
        next person to narrow the window would have watched their edit have no
        effect.

        Comparing against the real signature is the only version of this test
        that keeps working when the endpoint gains a parameter.
        """
        import inspect

        from routes.sync import pull_changes

        accepted = set(inspect.signature(pull_changes).parameters)

        seen = {}

        def _capture(*a, **k):
            # The warm-up ping carries no params; only record the real pull.
            if k.get("params"):
                seen.update(k["params"])
            return _FakeResponse({"changes": _cloud_snapshot([], paid_amount=0.0)})

        monkeypatch.setattr(SW, "_get_cloud_token", lambda _bid: "fake-token")
        monkeypatch.setattr(SW.httpx, "get", _capture)
        SW._LAST_PARITY.pop(BID, None)
        SW._cloud_parity_check(db, BID)

        assert seen, "parity made no parameterised request at all"
        unknown = set(seen) - accepted
        assert not unknown, (
            f"parity sends {sorted(unknown)}, which /api/sync/pull does not "
            f"declare — FastAPI will drop them and the caller will never know. "
            f"Accepted: {sorted(accepted)}"
        )

    def test_both_new_findings_are_in_the_summary_contract(self, db, monkeypatch):
        """The keys must exist even on a clean run.

        The total at the end of the sweep sums them; a KeyError there would be
        swallowed by the caller's `except Exception` and turn the whole sweep
        back into the silence it is being fixed for.
        """
        summary = _run_parity(db, monkeypatch, _cloud_snapshot([], paid_amount=0.0))
        assert "cloud_only" in summary
        assert "over_paid" in summary
