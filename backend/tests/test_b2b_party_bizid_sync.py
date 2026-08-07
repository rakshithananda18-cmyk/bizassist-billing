"""
tests/test_b2b_party_bizid_sync.py
==================================
B2B relationship rows name TWO businesses, and one of them is not you.

`b2b_connections` carries seller_business_id / buyer_business_id /
requested_by_business_id, and `b2b_orders` carries the first two. All five are
integer FKs into `users` — the one table that is deliberately never synced, and
the one FK target with no `uid` column (it identifies itself by `public_id`, the
BizID).

`_serialize_orm_obj` skipped every parent without a `uid`, so those columns
crossed the boundary as BARE SOURCE INTEGERS. The same business is id 7 on the
cloud and 126 locally, so on arrival they pointed at an unrelated local business
or at nothing, and SQLite with `foreign_keys=ON` refused the insert:

    b2b_connections uid c94c7cd5… — FOREIGN KEY constraint failed — Attempts: 7

and the order's line items then deferred forever, waiting on a parent order that
could never land. Observed as 9 of 11 permanently held inbox rows.

The re-point that DOES exist for `users` FKs (_USER_FK_REPOINT_ENTITIES) is the
wrong tool here: it rewrites the FK to the owner, which is correct for a shift's
`user_id` and a lie for a counterparty.
"""
import os
import sys
import uuid

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_bizassist.db")
os.environ.setdefault("GROQ_API_KEY", "mock_groq_api_key")

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, backend_path)

from fastapi.testclient import TestClient                 # noqa: E402
from main_groq import app                                 # noqa: E402
from database.db import SessionLocal                      # noqa: E402
from database.models import User, _serialize_orm_obj      # noqa: E402
from database.sync_map import resolve_parent_fk_uids      # noqa: E402
from core.models import B2BConnection                     # noqa: E402

client = TestClient(app)


def _signup(name):
    uname = f"b2b_{uuid.uuid4().hex[:8]}"
    r = client.post("/signup", json={
        "username": uname, "password": "TestPass123!", "business_name": name,
    })
    assert r.status_code == 200, r.text
    b = r.json()
    return (b["user"]["id"] if isinstance(b.get("user"), dict) else b["id"])


def _bizid(db, uid_):
    return db.query(User).filter(User.id == uid_).first().public_id


def test_the_serializer_sends_the_counterparty_bizid():
    """The sender's half. Without a BizID in the payload the receiver has
    nothing to resolve against, and no amount of work on the apply side can
    invent one."""
    seller = _signup("Seller Co")
    buyer = _signup("Buyer Co")
    db = SessionLocal()
    try:
        conn = B2BConnection(seller_business_id=seller, buyer_business_id=buyer,
                             requested_by_business_id=buyer, status="active")
        db.add(conn)
        db.commit()
        payload = _serialize_orm_obj(conn, db)

        assert payload["seller_business_id_bizid"] == _bizid(db, seller)
        assert payload["buyer_business_id_bizid"] == _bizid(db, buyer)
        assert payload["requested_by_business_id_bizid"] == _bizid(db, buyer)
        # The name rides along so an unknown counterparty can be stubbed with
        # something readable instead of a bare code.
        assert payload["seller_business_id_bizname"] == "Seller Co"
    finally:
        db.rollback()
        db.close()


def test_a_known_counterparty_resolves_to_its_local_id():
    """The integer in the payload is the SENDING database's. It must be replaced
    by this database's id for the same BizID — never written through."""
    seller = _signup("Seller Two")
    buyer = _signup("Buyer Two")
    db = SessionLocal()
    try:
        data = {
            # Deliberately absurd — these are "the other database's" integers.
            "seller_business_id": 999001,
            "buyer_business_id": 999002,
            "seller_business_id_bizid": _bizid(db, seller),
            "buyer_business_id_bizid": _bizid(db, buyer),
            "status": "active",
        }
        deferred = resolve_parent_fk_uids(db, B2BConnection, data,
                                          business_id=seller)
        assert deferred is False, "both parties exist locally — nothing to wait for"
        assert data["seller_business_id"] == seller
        assert data["buyer_business_id"] == buyer
    finally:
        db.rollback()
        db.close()


def test_an_unknown_counterparty_is_stubbed_not_dropped():
    """Accounts are never synced, so the other side of a B2B link is normally
    absent. Deferring forever would mean B2B never works cloud→local; attaching
    to some local business would be a cross-tenant link. A directory stub
    carrying the real BizID is the third option, and it is what the
    data-transfer path already does."""
    seller = _signup("Seller Three")
    stranger_bizid = f"BA-{uuid.uuid4().hex[:6].upper()}"
    db = SessionLocal()
    try:
        data = {
            "seller_business_id": 999003,
            "buyer_business_id": 999004,
            "seller_business_id_bizid": _bizid(db, seller),
            "buyer_business_id_bizid": stranger_bizid,
            "buyer_business_id_bizname": "Never Seen Traders",
            "status": "active",
        }
        deferred = resolve_parent_fk_uids(db, B2BConnection, data,
                                          business_id=seller)
        assert deferred is False

        stub = db.query(User).filter(User.public_id == stranger_bizid).first()
        assert stub is not None, "counterparty was neither resolved nor stubbed"
        assert data["buyer_business_id"] == stub.id
        assert stub.business_name == "Never Seen Traders"
        # A directory entry, not a login.
        assert stub.username.startswith("bizstub-")
    finally:
        db.rollback()
        db.close()


def test_the_same_bizid_never_creates_a_second_stub():
    """A stub carries the real BizID precisely so the next sync matches the same
    identity. Minting a fresh one per cycle would fan one counterparty out into
    a new phantom business every fifteen seconds."""
    seller = _signup("Seller Four")
    stranger_bizid = f"BA-{uuid.uuid4().hex[:6].upper()}"
    db = SessionLocal()
    try:
        for _ in range(3):
            data = {
                "seller_business_id": 999005,
                "buyer_business_id": 999006,
                "seller_business_id_bizid": _bizid(db, seller),
                "buyer_business_id_bizid": stranger_bizid,
                "status": "active",
            }
            assert resolve_parent_fk_uids(db, B2BConnection, data,
                                          business_id=seller) is False
        assert db.query(User).filter(User.public_id == stranger_bizid).count() == 1
    finally:
        db.rollback()
        db.close()


def test_a_payload_with_no_bizid_is_left_alone():
    """Older clients send no `_bizid`. The row must not be deferred forever, and
    must not be silently re-pointed at the owner either — that is the exact
    behaviour that is correct for a shift's user_id and wrong for a party."""
    seller = _signup("Seller Five")
    db = SessionLocal()
    try:
        data = {"seller_business_id": seller, "buyer_business_id": seller,
                "status": "active"}
        assert resolve_parent_fk_uids(db, B2BConnection, data,
                                      business_id=seller) is False
        assert data["seller_business_id"] == seller
    finally:
        db.rollback()
        db.close()


# ── seller_invoice_id: the column the party fix missed ───────────────────────
#
# 740b11e taught the serializer to emit a BizID for the two PARTY columns. It
# could not help `b2b_orders.seller_invoice_id`, which was declared as a bare
# `Column(Integer)` with no ForeignKey — and BOTH halves of the spine machinery
# iterate `__table__.foreign_keys`. With nothing to walk, the serializer emitted
# no uid and the resolver never inspected the column, so the sender's raw
# invoice id was written through verbatim.
#
# Measured on ORD-20260805-0001: the cloud sent seller_invoice_id=841 — its own
# id for the seller's B2B invoice. In the receiving database 841 is business
# 9999's load-test invoice LT-000015. The order pointed at another tenant's
# sale, which is the M-9 mis-link class on a money document.

def test_the_serializer_sends_the_seller_invoice_uid():
    from core.models import B2BOrder
    from core.billing import commands as billing

    seller = _signup("Inv Seller")
    buyer = _signup("Inv Buyer")
    db = SessionLocal()
    try:
        inv = billing.create_sale_invoice(
            db, business_id=seller, place_of_supply="29", invoice_no="SIU-1",
            lines=[{"product_name": "Thing", "quantity": 1, "unit_price": 100}])
        order = B2BOrder(seller_business_id=seller, buyer_business_id=buyer,
                         order_number=f"ORD-{uuid.uuid4().hex[:8]}",
                         order_date="2026-08-08", status="completed",
                         seller_invoice_id=inv.id)
        db.add(order)
        db.commit()

        payload = _serialize_orm_obj(order, db)
        assert payload["seller_invoice_id"] == inv.id
        # The durable half. Without this the receiver has only the sender's int.
        assert payload["seller_invoice_id_uid"] == inv.uid
    finally:
        db.rollback()
        db.close()


def test_a_foreign_seller_invoice_id_is_never_written_through():
    """The receiving database's 841 is not the sender's 841.

    `seller_invoice_id` is NULLABLE, so an unresolvable link follows the
    resolver's nullable rule: null it and keep the order, rather than defer a
    whole B2B order over a link that is only a convenience pointer. What must
    NEVER happen is the raw foreign integer surviving into the column.
    """
    from core.models import B2BOrder

    seller = _signup("Inv Seller Two")
    buyer = _signup("Inv Buyer Two")
    db = SessionLocal()
    try:
        data = {
            "seller_business_id": 999005,
            "buyer_business_id": 999006,
            "seller_business_id_bizid": _bizid(db, seller),
            "buyer_business_id_bizid": _bizid(db, buyer),
            "order_number": f"ORD-{uuid.uuid4().hex[:8]}",
            "order_date": "2026-08-08",
            "status": "completed",
            # The sender's id for ITS invoice, with no uid to resolve it here.
            "seller_invoice_id": 841,
        }
        resolve_parent_fk_uids(db, B2BOrder, data, business_id=seller)
        assert data["seller_invoice_id"] != 841, (
            "the sender's raw invoice id survived into the column — this is the "
            "mis-link that pointed an order at another tenant's invoice")
        assert data["seller_invoice_id"] is None
    finally:
        db.rollback()
        db.close()
