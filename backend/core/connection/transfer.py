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
  • existing connections/orders keep their destination state
  • orders match on order_number and verified business pair
  • lines match UID first, then a float-tolerant multiset; conflicts roll back
Composes within the caller's transaction — data_transfer.import_data owns the
commit, like every other command in this codebase.
"""
import logging
import uuid as _uuid
from collections import defaultdict
from sqlalchemy import func
from decimal import Decimal, InvalidOperation

from database.models import User, Invoice, Product
from core.models import B2BConnection, B2BOrder, B2BOrderLineItem

logger = logging.getLogger("bizassist.b2b_transfer")

B2B_RELATIONSHIP_TABLES = ("b2b_connections", "b2b_orders", "b2b_order_line_items")

# Helper columns added at export time; stripped before insert on import.
_EXPORT_ONLY_FIELDS = {"buyer_name", "seller_name",
                       "seller_invoice_no", "order_number_ref", "product_uid", "order_uid"}


class B2BImportConflict(ValueError):
    """A financial document cannot be safely merged; caller must roll back."""


def _number(value):
    try:
        number = Decimal(str(value if value is not None else 0))
    except (InvalidOperation, ValueError):
        raise B2BImportConflict("B2B document contains an invalid amount.") from None
    if not number.is_finite() or number < 0:
        raise B2BImportConflict("B2B document contains an invalid amount.")
    return number


def _same_line(source, target):
    # Float representations can differ after a SQLite/Postgres round trip.
    # Compare all financial fields, never just the displayed name and total.
    for key in ("quantity", "unit_price", "cgst_rate", "sgst_rate", "igst_rate", "line_total"):
        other = target.get(key) if isinstance(target, dict) else getattr(target, key)
        if abs(_number(source.get(key)) - _number(other)) > Decimal("0.000001"):
            return False
    return all(str(source.get(key) or default).strip().lower() ==
               str((target.get(key) if isinstance(target, dict) else getattr(target, key)) or default).strip().lower()
               for key, default in (("product_name", ""), ("unit", "Nos"), ("hsn_sac", "")))


def validate_new_orders(db, state):
    """Never commit a newly restored header with missing/conflicting children."""
    db.flush()
    for order_id in state.get("new_order_ids", ()):
        order = db.get(B2BOrder, order_id)
        lines = db.query(B2BOrderLineItem).filter_by(order_id=order_id).all()
        total = sum((_number(line.line_total) for line in lines), Decimal(0))
        if not lines or abs(total - _number(order.total_amount)) > Decimal("0.01"):
            raise B2BImportConflict("B2B order lines do not match the order total. Nothing was imported; reconcile the source order and retry.")


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
        s_biz, s_name = _bizid_of(db, bizids, c.seller_business_id)
        b_biz, b_name = _bizid_of(db, bizids, c.buyer_business_id)
        row["seller_bizid"] = getattr(c, "seller_bizid", None) or s_biz
        row["seller_name"] = s_name
        row["buyer_bizid"] = getattr(c, "buyer_bizid", None) or b_biz
        row["buyer_name"] = b_name
        out["b2b_connections"].append(row)

    orders = (
        db.query(B2BOrder)
        .filter((B2BOrder.seller_business_id == business_id)
                | (B2BOrder.buyer_business_id == business_id))
        .all()
    )
    for o in orders:
        row = _row_dict(o)
        s_biz, s_name = _bizid_of(db, bizids, o.seller_business_id)
        b_biz, b_name = _bizid_of(db, bizids, o.buyer_business_id)
        row["seller_bizid"] = getattr(o, "seller_bizid", None) or s_biz
        row["seller_name"] = s_name
        row["buyer_bizid"] = getattr(o, "buyer_bizid", None) or b_biz
        row["buyer_name"] = b_name
        # portable natural key for the completed order's seller invoice
        row["seller_invoice_no"] = None
        if o.seller_invoice_id:
            inv = db.query(Invoice).filter(Invoice.id == o.seller_invoice_id).first()
            row["seller_invoice_no"] = inv.invoice_id if inv else None
        out["b2b_orders"].append(row)

        for li in o.line_items:
            lrow = _row_dict(li)
            lrow["order_number_ref"] = o.order_number
            lrow["order_uid"] = o.uid
            lrow["seller_bizid"] = row["seller_bizid"]
            lrow["buyer_bizid"] = row["buyer_bizid"]
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
        u = db.query(User).filter(User.public_id == bizid, User.parent_business_id.is_(None)).first()
        if u is None and create_stub:
            try:
                from services.auth import hash_password
                u = User(
                    username=f"bizstub-{bizid.lower()}-{_uuid.uuid4().hex[:4]}",
                    password=hash_password(_uuid.uuid4().hex),  # unknowable
                    business_name=name or bizid,
                    public_id=bizid,
                )
                with db.begin_nested():
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


def _remap_requester(row: dict, *, seller_local: int, buyer_local: int):
    """Translate an exported ``requested_by_business_id`` into a LOCAL id.

    The exported value is a ``users.id`` from the source database. The only
    thing we can say about it reliably is whether it equalled that row's own
    seller or buyer there — so that is the only mapping we make. Anything else
    (a stale id, a third party, a missing field) becomes ``None``.

    ``None`` is the safe answer: under R3 a pending row with no recorded
    requester cannot be approved by anyone, so an unmappable value degrades to
    "ask again" rather than to "somebody gets to approve this".

    Pure — takes the raw row, returns an id or None. Unit-tested directly.
    """
    raw = row.get("requested_by_business_id")
    if raw is None:
        return None
    src_seller = row.get("seller_business_id")
    src_buyer = row.get("buyer_business_id")
    if src_seller is not None and raw == src_seller:
        return seller_local
    if src_buyer is not None and raw == src_buyer:
        return buyer_local
    return None


def _claim_uid(db, data: dict, model) -> dict:
    """Keep the source row's ``uid`` only if it is FREE in this database.

    ``uid`` is the durable cross-DB key the B2B cloud→local mirror matches on,
    and it now carries a partial-unique index. Preserving it across a transfer is
    what makes a re-import idempotent — but an export can legitimately be
    reshaped before import (a row re-pointed at a different counterparty is a
    DIFFERENT relationship, yet still carries the original uid). Inserting that
    verbatim collides on the unique index and 500s the whole import.

    So: reuse the uid when it is unclaimed, mint a fresh one when it is taken.
    Genuine transfers keep stable identity; reshaped rows get their own.
    """
    uid = data.get("uid")
    if not uid:
        data.pop("uid", None)          # let the column default mint one
        return data
    try:
        taken = db.query(model.id).filter(model.uid == uid).first() is not None
    except Exception as exc:
        # NOT a silent `taken = False`. Assuming the uid is free after a FAILED
        # lookup is the worst of the two guesses: it inserts a possibly-colliding
        # uid and 500s the whole import on the partial unique index — the exact
        # outcome this function exists to prevent. Mint a fresh uid instead (the
        # safe direction: a genuine transfer loses uid stability, nothing breaks)
        # and say so, because a uniqueness check that failed must never look like
        # a uniqueness check that passed (architecture rule 13).
        logger.error(
            "[B2B_TRANSFER] uid-availability check FAILED for %s uid=%s (%s) — "
            "minting a fresh uid; this row will not match its source across "
            "databases", model.__name__, uid, exc)
        data["uid"] = str(_uuid.uuid4())
        return data
    if taken:
        data["uid"] = str(_uuid.uuid4())
    return data


def import_b2b_tables(db, table_name: str, rows: list, dest_owner_id: int,
                      skipped_out: list = None, state: dict = None) -> int:
    """Upsert one B2B relationship table from an export payload. Returns the
    number of rows APPLIED (created or updated).

    ``skipped_out`` — pass a list to receive one dict per row that was NOT
    imported, with the reason. This is not diagnostics; it is half the result.

    WHY (review finding M-19). The skip count used to be logged and then
    **discarded** — the function returned `applied` only, and
    `routes/data_transfer.py` reported that as `imported[table] = n`. So an import
    that dropped a connection, an order, or a line item told the operator "42
    rows imported" and nothing else, while the rows were gone. That is the
    M-12/M-13 pattern in a third venue: a partial operation reporting success.

    The skips matter individually, too. A line item dropped because its product
    is absent leaves the order's lines no longer summing to its header — the
    M-18 invariant, broken from the under-filled side, by this importer.
    """
    users: dict = {}
    applied = skipped = 0
    skipped_out = skipped_out if skipped_out is not None else []
    state = state if state is not None else {}
    owner = db.get(User, dest_owner_id)

    def _owns(row):
        return owner is not None and owner.public_id in (
            row.get("seller_bizid"), row.get("buyer_bizid"))

    def _skip(kind: str, reason: str, **ident):
        skipped_out.append({"table": table_name, "kind": kind,
                            "reason": reason, **ident})

    if table_name == "b2b_connections":
        for row in rows:
            if not row.get("seller_bizid") or not row.get("buyer_bizid"):
                _skip("connection", "party unresolvable in this database")
                skipped += 1
                continue
            if row.get("seller_bizid") and row.get("buyer_bizid") and not _owns(row):
                _skip("connection", "relationship does not belong to this business")
                skipped += 1
                continue
            seller = _resolve_user(db, users, row.get("seller_bizid"), row.get("seller_name"))
            buyer = _resolve_user(db, users, row.get("buyer_bizid"), row.get("buyer_name"))
            if not seller or not buyer:
                skipped += 1
                _skip("connection", "party unresolvable in this database",
                      seller_bizid=row.get("seller_bizid"),
                      buyer_bizid=row.get("buyer_bizid"))
                logger.warning("[B2B_TRANSFER] skip connection %s<->%s — party unresolvable",
                               row.get("seller_bizid"), row.get("buyer_bizid"))
                continue
            data = _clean(row, B2BConnection)
            # `requested_by_business_id` is a users.id in the SOURCE database and
            # is meaningless here — carrying it verbatim would name whichever
            # local business happens to hold that integer as the requester. That
            # is a consent bug, not just bad data: name the counterparty as
            # requester and the importer can "approve" a link nobody asked for.
            # Re-point it through the same mapping as the two parties; anything
            # we cannot map becomes NULL, which fails closed under R3.
            data["requested_by_business_id"] = _remap_requester(
                row, seller_local=seller, buyer_local=buyer)
            data["seller_business_id"], data["buyer_business_id"] = seller, buyer
            data["seller_bizid"] = row.get("seller_bizid")
            data["buyer_bizid"] = row.get("buyer_bizid")
            existing = (
                db.query(B2BConnection)
                .filter(B2BConnection.seller_business_id == seller,
                        B2BConnection.buyer_business_id == buyer)
                .first()
            )
            if not existing:
                db.add(B2BConnection(**_claim_uid(db, data, B2BConnection)))
                db.flush()
            applied += 1

    elif table_name == "b2b_orders":
        for row in rows:
            if not row.get("seller_bizid") or not row.get("buyer_bizid"):
                _skip("order", "party unresolvable in this database", order_number=row.get("order_number"))
                skipped += 1
                continue
            if row.get("seller_bizid") and row.get("buyer_bizid") and not _owns(row):
                raise B2BImportConflict("B2B order does not belong to this business.")
            seller = _resolve_user(db, users, row.get("seller_bizid"), row.get("seller_name"))
            buyer = _resolve_user(db, users, row.get("buyer_bizid"), row.get("buyer_name"))
            if not seller or not buyer:
                skipped += 1
                _skip("order", "party unresolvable in this database",
                      order_number=row.get("order_number"))
                logger.warning("[B2B_TRANSFER] skip order %s — party unresolvable",
                               row.get("order_number"))
                continue
            data = _clean(row, B2BOrder)
            data["seller_business_id"], data["buyer_business_id"] = seller, buyer
            data["seller_bizid"] = row.get("seller_bizid")
            data["buyer_bizid"] = row.get("buyer_bizid")
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
                if (existing.seller_business_id != seller or existing.buyer_business_id != buyer
                        or abs(_number(existing.total_amount) - _number(data.get("total_amount"))) > Decimal("0.01")):
                    raise B2BImportConflict("B2B order identity or total conflicts with the destination. Nothing was imported; reconcile the order and retry.")
                # Backup import only adds missing data. Existing status, balance
                # and consent are authoritative; edits belong to the sync worker.
            else:
                _number(data.get("total_amount"))
                if data.get("uid") and db.query(B2BOrder.id).filter_by(uid=data["uid"]).first():
                    raise B2BImportConflict("B2B order identity is already assigned to a different order.")
                new_order = B2BOrder(**data)
                db.add(new_order)
                db.flush()
                state.setdefault("new_order_ids", set()).add(new_order.id)
            applied += 1
        db.flush()   # line items (next table in order) need the new order ids

    elif table_name == "b2b_order_line_items":
        groups = defaultdict(list)
        for row in rows:
            groups[row.get("order_number_ref")].append(row)
        for order_number, group in groups.items():
            order = (
                db.query(B2BOrder)
                .filter(B2BOrder.order_number == order_number,
                        (B2BOrder.seller_business_id == dest_owner_id)
                        | (B2BOrder.buyer_business_id == dest_owner_id))
                .with_for_update()
                .first()
            )
            if order is None:
                for row in group:
                    skipped += 1
                    _skip("order_line", "parent order not present in this database",
                          order_number=order_number)
                continue
            existing_lines = db.query(B2BOrderLineItem).filter_by(order_id=order.id).all()
            unmatched = list(existing_lines)
            pending, seen_uids = [], {}
            seller_id = db.get(User, order.seller_business_id).public_id
            buyer_id = db.get(User, order.buyer_business_id).public_id
            for row in group:
                if any(row.get(key) and row[key] != value for key, value in
                       (("seller_bizid", seller_id), ("buyer_bizid", buyer_id))):
                    raise B2BImportConflict("B2B line belongs to a different business pair.")
                uid = row.get("uid")
                if uid in seen_uids:
                    if not _same_line(row, seen_uids[uid]):
                        raise B2BImportConflict("B2B line identity has conflicting amounts.")
                    continue
                if uid:
                    seen_uids[uid] = row
                by_uid = db.query(B2BOrderLineItem).filter_by(uid=uid).first() if uid else None
                if by_uid is not None:
                    if by_uid.order_id != order.id or not _same_line(row, by_uid):
                        raise B2BImportConflict("B2B line identity conflicts with the destination.")
                    if by_uid in unmatched:
                        unmatched.remove(by_uid)
                    continue
                # Multiset matching retains two legitimate identical lines while
                # recognising older copies that did not preserve durable UIDs.
                match = next((line for line in unmatched if _same_line(row, line)), None)
                if match is not None:
                    unmatched.remove(match)
                    continue
                product = None
                if row.get("product_uid"):
                    product = db.query(Product).filter_by(
                        uid=row["product_uid"], business_id=order.seller_business_id).first()
                if product is None and row.get("product_name"):
                    pname = str(row["product_name"]).strip()
                    product = db.query(Product).filter_by(
                        name=row["product_name"], business_id=order.seller_business_id).first()
                    if product is None:
                        product = db.query(Product).filter(
                            func.lower(func.trim(Product.name)) == pname.lower(),
                            Product.business_id == order.seller_business_id,
                        ).first()
                if product is None:
                    raise B2BImportConflict("B2B order product is missing from the seller catalogue. Nothing was imported; restore the products and retry.")
                # Validate even a zero-total header (the database guard exempts it).
                _same_line(row, row)
                data = _clean(row, B2BOrderLineItem)
                data["order_id"], data["product_id"] = order.id, product.id
                pending.append(data)
            current = sum((_number(line.line_total) for line in existing_lines), Decimal(0))
            addition = sum((_number(line["line_total"]) for line in pending), Decimal(0))
            if pending and abs(current - _number(order.total_amount)) <= Decimal("0.01"):
                # Destination already holds the complete billed order lines; ignore redundant incoming items
                pending.clear()
            elif pending and current + addition > _number(order.total_amount) + Decimal("0.01"):
                raise B2BImportConflict("B2B order already contains billed lines or has conflicting totals. Nothing was imported; reconcile the order and retry.")
            # No dangerous rows are pending before entering the savepoint.
            with db.begin_nested():
                for data in pending:
                    db.add(B2BOrderLineItem(**data))
                db.flush()
            applied += len(pending)

    if skipped:
        # ERROR, not INFO: these rows are MISSING from this database.
        logger.error(
            "[B2B_TRANSFER] import %s: applied=%s but SKIPPED=%s — those rows are "
            "not in this database: %s",
            table_name, applied, skipped, skipped_out)
    elif applied:
        logger.info("[B2B_TRANSFER] import %s applied=%s dest_owner=%s",
                    table_name, applied, dest_owner_id)
    return applied
