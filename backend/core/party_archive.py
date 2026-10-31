"""Immutable document parties and non-login identities for retired B2B accounts.

An account retirement must not erase a partner's financial history. These helpers
compose in the caller's transaction; they never commit or resurrect an account.
"""
from __future__ import annotations

import json
import logging
import uuid

from sqlalchemy import Boolean, Column, ForeignKey, Integer, String, Text, UniqueConstraint, or_
from sqlalchemy.orm import object_session

from database.db import Base, TimestampMixin
from services.dates import utc_now

logger = logging.getLogger("bizassist.parties.archive")


class DocumentPartySnapshot(Base, TimestampMixin):
    __tablename__ = "document_party_snapshots"
    id = Column(Integer, primary_key=True)
    uid = Column(String(36), nullable=False, default=lambda: str(uuid.uuid4()), unique=True)
    business_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    document_kind = Column(String(20), nullable=False)
    document_uid = Column(String(36), nullable=False, index=True)
    seller_bizid = Column(String, nullable=True, index=True)
    buyer_bizid = Column(String, nullable=True, index=True)
    seller_json = Column(Text, nullable=False)
    buyer_json = Column(Text, nullable=False)
    origin = Column(String(24), nullable=False, default="posted")
    seller_deleted = Column(Boolean, nullable=False, default=False, server_default="0")
    buyer_deleted = Column(Boolean, nullable=False, default=False, server_default="0")
    __table_args__ = (UniqueConstraint("business_id", "document_kind", "document_uid", name="uq_document_party_snapshot"),)


def party_details(party) -> dict:
    if isinstance(party, dict):
        return dict(party)
    if party is None:
        return {}
    return {
        "name": getattr(party, "business_name", None) or getattr(party, "name", None) or "Business",
        "biz_id": getattr(party, "public_id", None),
        "gstin": getattr(party, "gstin", None),
        "address": getattr(party, "address", None),
        "phone": getattr(party, "phone", None),
        "email": getattr(party, "email", None),
        "state_code": getattr(party, "state_code", None),
        "pan": getattr(party, "pan", None),
    }


def decode_party(raw) -> dict:
    if isinstance(raw, dict):
        return raw
    try:
        value = json.loads(raw or "{}")
        return value if isinstance(value, dict) else {}
    except (TypeError, ValueError):
        return {}


def is_deleted_user(user) -> bool:
    if isinstance(user, dict):
        return bool(user.get("account_deleted") or user.get("deleted")
                    or str(user.get("role") or "").lower() in {"deleted", "retired"})
    return bool(user is not None and (getattr(user, "role", None) or "").lower() in {"deleted", "retired"})


def is_business_deleted(db, business_id: int) -> bool:
    from database.models import User
    from core.models import B2BConnection
    from database.trade_service import business_profile
    user = business_profile(db, id=business_id)
    if user is None or is_deleted_user(user):
        return True
    # Counterparty account rows are not replicated. A trusted mirrored retired
    # flag must therefore close the same identity locally without a User update.
    return db.query(B2BConnection.id).filter(or_(
        (B2BConnection.seller_business_id == business_id) & B2BConnection.seller_deleted.is_(True),
        (B2BConnection.buyer_business_id == business_id) & B2BConnection.buyer_deleted.is_(True),
    )).first() is not None


def require_active_businesses(db, *business_ids) -> None:
    for business_id in set(business_ids):
        if business_id is None or is_business_deleted(db, business_id):
            raise ValueError("This business account has been deleted. Historical documents remain available, but new trade is disabled.")


def capture_order_parties(db, order, buyer, seller) -> None:
    for side, user in (("buyer", buyer), ("seller", seller)):
        field = side + "_snapshot"
        if not getattr(order, field, None):
            setattr(order, field, json.dumps(party_details(user), sort_keys=True))
        if not getattr(order, side + "_bizid", None):
            setattr(order, side + "_bizid", getattr(user, "public_id", None))


def capture_document_parties(db, document, *, kind: str, seller, buyer, origin="posted"):
    if kind not in {"sale", "purchase"}:
        raise ValueError("Unsupported financial document kind")
    if not getattr(document, "uid", None):
        document.uid = str(uuid.uuid4())
    existing = db.query(DocumentPartySnapshot).filter_by(
        business_id=document.business_id, document_kind=kind, document_uid=document.uid,
    ).first()
    if existing is not None:
        return existing
    seller_data, buyer_data = party_details(seller), party_details(buyer)
    row = DocumentPartySnapshot(
        business_id=document.business_id, document_kind=kind, document_uid=document.uid,
        seller_bizid=seller_data.get("biz_id"), buyer_bizid=buyer_data.get("biz_id"),
        seller_json=json.dumps(seller_data, sort_keys=True), buyer_json=json.dumps(buyer_data, sort_keys=True),
        seller_deleted=is_deleted_user(seller), buyer_deleted=is_deleted_user(buyer), origin=origin,
    )
    db.add(row)
    return row


def document_party_metadata(document, kind="sale") -> dict:
    db = object_session(document)
    if db is None or not getattr(document, "uid", None):
        return {}
    row = db.query(DocumentPartySnapshot).filter_by(
        business_id=document.business_id, document_kind=kind, document_uid=document.uid,
    ).first()
    if row is None:
        return {}
    return {
        "parties": {"seller": decode_party(row.seller_json), "buyer": decode_party(row.buyer_json)},
        "seller_deleted": bool(row.seller_deleted), "buyer_deleted": bool(row.buyer_deleted),
        "counterparty_deleted": bool(row.buyer_deleted if kind == "sale" else row.seller_deleted),
        "party_snapshot_origin": row.origin,
    }


def archive_shared_history(db, business_id: int, *, retiring: bool = True) -> bool:
    """Freeze parties, detach deletable product/document FKs and retain the deal.

    Returns whether a minimal User identity must remain to satisfy shared FKs.
    Caller must revoke/delete credentials and private records in the same txn.
    """
    from database.models import User, Invoice, PurchaseInvoice
    from core.models import B2BConnection, B2BOrder, B2BOrderLineItem, B2BLedger
    orders = db.query(B2BOrder).filter(or_(
        B2BOrder.seller_business_id == business_id, B2BOrder.buyer_business_id == business_id,
    )).all()
    connections = db.query(B2BConnection).filter(or_(
        B2BConnection.seller_business_id == business_id, B2BConnection.buyer_business_id == business_id,
    )).all()
    for row in [*orders, *connections]:
        seller, buyer = db.get(User, row.seller_business_id), db.get(User, row.buyer_business_id)
        capture_order_parties(db, row, buyer, seller)
        if retiring and row.seller_business_id == business_id:
            row.seller_deleted = True
        if retiring and row.buyer_business_id == business_id:
            row.buyer_deleted = True
        row.updated_at = utc_now()
    for order in orders:
        sale = db.get(Invoice, order.seller_invoice_id) if order.seller_invoice_id else None
        seller, buyer = db.get(User, order.seller_business_id), db.get(User, order.buyer_business_id)
        if sale is not None:
            capture_document_parties(db, sale, kind="sale", seller=seller, buyer=buyer, origin="retirement_legacy")
            order.seller_invoice_uid = sale.uid
            order.seller_invoice_number = sale.invoice_id
            # Preserve the buyer's independently owned bill and its own identity
            # snapshot even when the original issuer's account is retired.
            from core.order.service import b2b_purchase_invoice_uid
            purchase = db.query(PurchaseInvoice).filter_by(
                business_id=order.buyer_business_id, uid=b2b_purchase_invoice_uid(order),
            ).first()
            if purchase is not None:
                capture_document_parties(db, purchase, kind="purchase", seller=seller, buyer=buyer, origin="retirement_legacy")
        if order.seller_business_id == business_id:
            order.seller_invoice_id = None
        if order.status not in {"completed", "cancelled", "rejected"}:
            order.status = "cancelled"
            order.notes = ((order.notes or "") + "\nCancelled: a business account was deleted.").strip()
        if order.seller_business_id == business_id:
            for line in order.line_items:
                line.product_id = None
    for connection in connections:
        connection.status = "revoked"
        connection.responded_at = utc_now()
    db.flush()
    owner = db.get(User, business_id)
    if retiring and owner is not None and owner.public_id:
        for row in db.query(DocumentPartySnapshot).filter(or_(
            DocumentPartySnapshot.seller_bizid == owner.public_id,
            DocumentPartySnapshot.buyer_bizid == owner.public_id,
        )).all():
            if row.seller_bizid == owner.public_id:
                row.seller_deleted = True
            if row.buyer_bizid == owner.public_id:
                row.buyer_deleted = True
        # Flush before the caller bulk-deletes this owner's private snapshots;
        # otherwise dirty ORM instances would try to update those deleted rows
        # at commit and roll the entire retirement back with StaleDataError.
        db.flush()
    ledger_exists = db.query(B2BLedger.id).filter(or_(
        B2BLedger.seller_business_id == business_id, B2BLedger.buyer_business_id == business_id,
    )).first() is not None
    if orders or connections or ledger_exists:
        logger.info("[ARCHIVE] retained shared history biz=%s orders=%s connections=%s", business_id, len(orders), len(connections))
        return True
    return False


def retire_identity(user) -> None:
    """Keep only a non-login directory tombstone; never recycle its BizID."""
    user.username = "retired-" + uuid.uuid4().hex
    user.password = "!retired:" + uuid.uuid4().hex
    user.role = "deleted"
    user.token_version = int(user.token_version or 0) + 1
    user.settings = json.dumps({"account_deleted": True})
    for field in ("phone", "email", "address", "gstin", "pan", "logo", "upi_vpa", "counter_prefix", "staff_login_name"):
        setattr(user, field, None)
    user.is_premium = False
    user.last_login = None
