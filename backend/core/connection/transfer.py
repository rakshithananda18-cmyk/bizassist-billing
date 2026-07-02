"""
core/connection/transfer.py — B2B relationship data in export/import (bug fix).
===============================================================================
WHY THIS EXISTS: the generic data-transfer pipeline scopes every table by its
`business_id` column. The B2B relationship tables (`b2b_connections`,
`b2b_orders`, `b2b_order_line_items`) are TWO-SIDED — they carry
`buyer_business_id` + `seller_business_id` (users.id), so the generic path
exported nothing for them and any local↔cloud migration silently dropped the
business's B2B network and order history (the seller invoice, a normal
single-tenant row, DID transfer — which is how an order can appear in Payments
but not in B2B Orders).

Identity across databases: integer user ids differ per DB (local id=122,
cloud id=7), so rows are exported with portable identity keys and re-resolved
on import:
  • buyer_bizid / seller_bizid   → users.public_id (the BizID)
  • seller_invoice_no            → invoices.invoice_id (natural key)
  • order_number (on line items) → parent order natural key
  • product_uid / product_name   → product re-resolution for line items

Import is defensive and idempotent:
  • a side whose BizID doesn't exist in the destination → row skipped + logged
    (never a crash, never a dangling FK)
  • connections upsert on (seller_business_id, buyer_business_id)
  • orders upsert on order_number
  • line items inserted only when the parent order is newly created here
Composes within the caller's transaction — data_transfer.import_data owns the
commit, like every other command in this codebase.
"""
import logging
import uuid as _uuid

from database.models import User, Invoice, Product
from core.models import B2BConnection, B2BOrder, B2BOrderLineItem

logger = logging.getLogger("bizassist.b2b_transfer")

B2B_RELATIONSHIP_TABLES = ("b2b_connections", "b2b_orders", "b2b_order_line_items")

# Helper columns added at export time; stripped before insert on import.
_EXPORT_ONLY_FIELDS = {"buyer_bizid", "seller_bizid", "buyer_name", "seller_name",
                       "seller_invoice_no", "order_number_ref", "product_uid"}


def _row_dict(obj) -> dict:
    return {c.name: getattr(obj, c.name) for c in obj.__table__.columns}


def _bizid_of(db, cache: dict, user_id: int):
    if user_id not in cache:
        u = db.query(User).filter(User.id == user_id).first()
        cache[user_id] = (u.public_id, u.business_name) if u else (None, None)
    return cache[user_id]


# ── EXPORT ────────────────────────────────────────────────────────────────────

def export_b2b_tables(db, business_id: int) -> dict:
    """All B2B relationship rows where this business is buyer OR seller,
    augmented with portable identity keys. Returns {table: [rows]}."""
    bizids: dict = {}
    out = {t: [] for t in B2B_RELATIONSHIP_TABLES}

    conns = (
        db.query(B2BConnection)
        .filter((B2BConnection.seller_business_id == business_id)
                | (B2BConnection.buyer_business_id == business_id))
        .all()
    )
    for c in conns:
        row = _row_dict(c)
        row["seller_bizid"], row["seller_name"] = _bizid_of(db, bizids, c.seller_business_id)
        row["buyer_bizid"], row["buyer_name"] = _bizid_of(db, bizids, c.buyer_business_id)
        out["b2b_connections"].append(row)

    orders = (
        db.query(B2BOrder)
        .filter((B2BOrder.seller_business_id == business_id)
                | (B2BOrder.buyer_business_id == business_id))
        .all()
    )
    for o in orders:
        row = _row_dict(o)
        row["seller_bizid"], row["seller_name"] = _bizid_of(db, bizids, o.seller_business_id)
        row["buyer_bizid"], row["buyer_name"] = _bizid_of(db, bizids, o.buyer_business_id)
        # portable natural key for the completed order's seller invoice
        row["seller_invoice_no"] = None
        if o.seller_invoice_id:
            inv = db.query(Invoice).filter(Invoice.id == o.seller_invoice_id).first()
            row["seller_invoice_no"] = inv.invoice_id if inv else None
        out["b2b_orders"].append(row)

        for li in o.line_items:
            lrow = _row_dict(li)
            lrow["order_number_ref"] = o.order_number
            p = db.query(Product).filter(Product.id == li.product_id).first()
            lrow["product_uid"] = getattr(p, "uid", None) if p else None
            out["b2b_order_line_items"].append(lrow)

    counts = {k: len(v) for k, v in out.items() if v}
    if counts:
        logger.info("[B2B_TRANSFER] export biz=%s %s", business_id, counts)
    return out


# ── IMPORT ────────────────────────────────────────────────────────────────────

def _resolve_user(db, cache: dict, bizid, name=None, create_stub=True):
    """BizID → destination user id.

    When the counterparty account doesn't exist in this DB (the normal case for
    a Cloud→Local sync — accounts are never synced, only business data), a
    minimal COUNTERPARTY STUB is created so the relationship rows stay valid
    and the B2B pages can show names. The stub carries the real BizID (so a
    later cloud sync matches the same identity), the display name, and an
    unknowable random password — it is a directory entry, not a login.
    """
    if not bizid:
        return None
    if bizid not in cache:
        u = db.query(User).filter(User.public_id == bizid).first()
        if u is None and create_stub:
            try:
                from services.auth import hash_password
                u = User(
                    username=f"bizstub-{bizid.lower()}-{_uuid.uuid4().hex[:4]}",
                    password=hash_password(_uuid.uuid4().hex),  # unknowable
                    business_name=name or bizid,
                    public_id=bizid,
                )
                db.add(u)
                db.flush()
                logger.info("[B2B_TRANSFER] created counterparty stub %s (%s) id=%s",
                            bizid, name or "?", u.id)
            except Exception as exc:
                logger.warning("[B2B_TRANSFER] could not create stub for %s — %s", bizid, exc)
                u = None
        cache[bizid] = u.id if u else None
    return cache[bizid]


def _clean(row: dict, model) -> dict:
    """Strip export-only helpers, the source PK, datetime columns (they arrive
    as ISO strings in JSON — let the column defaults stamp them), and unknown
    columns."""
    cols = {c.name for c in model.__table__.columns}
    return {k: v for k, v in row.items()
            if k in cols
            and k not in ("id", "created_at", "updated_at")
            and k not in _EXPORT_ONLY_FIELDS}


def import_b2b_tables(db, table_name: str, rows: list, dest_owner_id: int) -> int:
    """Upsert one B2B relationship table from an export payload. Returns the
    number of rows applied (created or updated); skips are logged, never fatal."""
    users: dict = {}
    applied = skipped = 0

    if table_name == "b2b_connections":
        for row in rows:
            seller = _resolve_user(db, users, row.get("seller_bizid"), row.get("seller_name"))
            buyer = _resolve_user(db, users, row.get("buyer_bizid"), row.get("buyer_name"))
            if not seller or not buyer:
                skipped += 1
                logger.warning("[B2B_TRANSFER] skip connection %s↔%s — party unresolvable",
                               row.get("seller_bizid"), row.get("buyer_bizid"))
                continue
            data = _clean(row, B2BConnection)
            data["seller_business_id"], data["buyer_business_id"] = seller, buyer
            existing = (
                db.query(B2BConnection)
                .filter(B2BConnection.seller_business_id == seller,
                        B2BConnection.buyer_business_id == buyer)
                .first()
            )
            if existing:
                for k in ("price_tier", "discount_pct", "credit_limit",
                          "outstanding_balance", "stock_visibility",
                          "catalog_category", "status"):
                    if k in data and data[k] is not None:
                        setattr(existing, k, data[k])
            else:
                db.add(B2BConnection(**data))
            applied += 1

    elif table_name == "b2b_orders":
        for row in rows:
            seller = _resolve_user(db, users, row.get("seller_bizid"), row.get("seller_name"))
            buyer = _resolve_user(db, users, row.get("buyer_bizid"), row.get("buyer_name"))
            if not seller or not buyer:
                skipped += 1
                logger.warning("[B2B_TRANSFER] skip order %s — party unresolvable",
                               row.get("order_number"))
                continue
            data = _clean(row, B2BOrder)
            data["seller_business_id"], data["buyer_business_id"] = seller, buyer
            # seller_invoice_id: source PK is meaningless here — re-resolve via
            # the invoice's natural number within the SELLER's business.
            data["seller_invoice_id"] = None
            if row.get("seller_invoice_no"):
                inv = (
                    db.query(Invoice)
                    .filter(Invoice.business_id == seller,
                            Invoice.invoice_id == row["seller_invoice_no"])
                    .first()
                )
                data["seller_invoice_id"] = inv.id if inv else None
            existing = (
                db.query(B2BOrder)
                .filter(B2BOrder.order_number == row.get("order_number"))
                .first()
            )
            if existing:
                if data.get("status"):
                    existing.status = data["status"]
                if data.get("seller_invoice_id") and not existing.seller_invoice_id:
                    existing.seller_invoice_id = data["seller_invoice_id"]
            else:
                db.add(B2BOrder(**data))
            applied += 1
        db.flush()   # line items (next table in order) need the new order ids

    elif table_name == "b2b_order_line_items":
        for row in rows:
            order = (
                db.query(B2BOrder)
                .filter(B2BOrder.order_number == row.get("order_number_ref"))
                .first()
            )
            if order is None:
                skipped += 1
                continue
            # Idempotency per line (not per parent — several lines of the same
            # new order import in one pass): same order + name + qty + total
            # already present → nothing to do.
            dup = (
                db.query(B2BOrderLineItem)
                .filter(B2BOrderLineItem.order_id == order.id,
                        B2BOrderLineItem.product_name == row.get("product_name"),
                        B2BOrderLineItem.quantity == row.get("quantity"),
                        B2BOrderLineItem.line_total == row.get("line_total"))
                .first()
            )
            if dup is not None:
                continue
            product = None
            if row.get("product_uid"):
                product = db.query(Product).filter(Product.uid == row["product_uid"]).first()
            if product is None and row.get("product_name"):
                product = (
                    db.query(Product)
                    .filter(Product.business_id == order.seller_business_id,
                            Product.name == row["product_name"])
                    .first()
                )
            if product is None:
                skipped += 1
                logger.warning("[B2B_TRANSFER] skip line '%s' on %s — product not in this DB",
                               row.get("product_name"), row.get("order_number_ref"))
                continue
            data = _clean(row, B2BOrderLineItem)
            data["order_id"], data["product_id"] = order.id, product.id
            db.add(B2BOrderLineItem(**data))
            applied += 1

    if applied or skipped:
        logger.info("[B2B_TRANSFER] import %s applied=%s skipped=%s dest_owner=%s",
                    table_name, applied, skipped, dest_owner_id)
    return applied
