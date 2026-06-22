"""
core/api/sync.py — offline-first delta PULL (R7b, Slice 2).
==========================================================
The offline client keeps a local cache and needs to learn "what changed on the
server since I last looked" — new sales/payments/purchases/stock moves it didn't
make itself, or that it made on another device. This is the PULL half of sync
(the PUSH half is Slice 1's `X-Client-Request-Id` replay wall + the client
outbox in Slice 3).

DESIGN — derived feed, per-entity autoincrement-id cursor.
Rather than maintain a separate `sync_log` table that every money command must
write to (another money-path touch, and a log that can drift from the truth),
we DERIVE the feed by reading the append-only source tables directly. Each
tenant-scoped table has a strictly-monotonic autoincrement `id`, so "give me
rows with id > my_cursor" delivers every new row exactly once, gap-free, and can
NEVER drift from the source of truth. The cursor is a small per-entity map:

    GET /sync/pull?since={"invoice":120,"payment":45,"purchase":7,"stock":300}
    →  { "changes": { "invoice":[…], "payment":[…], "purchase":[…], "stock":[…] },
         "cursor":  { "invoice":131, "payment":45, "purchase":7, "stock":312 },
         "has_more": false, "limit": 500 }

The client persists `cursor` and sends it back next time. `has_more=true` means
at least one entity hit the page cap → pull again immediately to drain the
backlog. Missing cursor keys default to 0 (full backfill on first sync).

SCOPE (Slice 2): the append-only MONEY entities — invoice, payment, purchase,
stock — which are what an offline counter most needs to reconcile. In-place
catalog edits (product/customer price/name changes) are NOT id-monotonic on
change, so syncing those needs an `updated_at` watermark — deferred to a later
slice. Header-level invoice/purchase fields only; full line-item hydration is
available via the existing detail endpoints and deferred here to keep the feed
cheap (no N+1).

Tenant-scoped: every query filters `business_id == caller`. A cursor value is
per-tenant — business A's `invoice:120` and business B's `invoice:120` are
unrelated high-water marks over each tenant's own rows.
"""
import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from database.db import get_db
from database.models import Invoice, InvoicePayment, PurchaseInvoice
from core.models import StockLedger
from services.auth import get_active_user

router = APIRouter()
logger = logging.getLogger("bizassist.sync")

DEFAULT_LIMIT = 500
MAX_LIMIT = 2000

ENTITIES = ("invoice", "payment", "purchase", "stock")


def _iso(dt):
    return dt.isoformat() if dt else None


def _invoice_out(inv: Invoice) -> dict:
    return {
        "id": inv.id,
        "invoice_no": inv.invoice_id,
        "customer": inv.customer,
        "invoice_date": inv.invoice_date,
        "status": inv.status,
        "subtotal": inv.subtotal,
        "total_amount": inv.total_amount,
        "paid_amount": inv.paid_amount,
        "created_at": _iso(inv.created_at),
    }


def _payment_out(p: InvoicePayment) -> dict:
    return {
        "id": p.id,
        "invoice_id": p.invoice_id,
        "customer_id": p.customer_id,
        "amount_paid": p.amount_paid,
        "payment_mode": p.payment_mode,
        "payment_date": p.payment_date,
        "note": p.note,
        "created_at": _iso(p.created_at),
    }


def _purchase_out(pi: PurchaseInvoice) -> dict:
    return {
        "id": pi.id,
        "supplier_name": pi.supplier_name,
        "invoice_number": pi.invoice_number,
        "invoice_date": pi.invoice_date,
        "status": pi.status,
        "total_amount": pi.total_amount,
        "created_at": _iso(pi.created_at),
    }


def _stock_out(s: StockLedger) -> dict:
    return {
        "id": s.id,
        "product_id": s.product_id,
        "product_name": s.product_name,
        "movement_type": s.movement_type,
        "qty_delta": s.qty_delta,
        "balance_after": s.balance_after,
        "reference_type": s.reference_type,
        "reference_id": s.reference_id,
        "created_at": _iso(s.created_at),
    }


# (cursor key, Model, serializer)
_FEED = (
    ("invoice",  Invoice,         _invoice_out),
    ("payment",  InvoicePayment,  _payment_out),
    ("purchase", PurchaseInvoice, _purchase_out),
    ("stock",    StockLedger,     _stock_out),
)


def _parse_since(since: Optional[str]) -> dict:
    """Parse the JSON cursor map defensively. Bad/absent input → empty (full backfill)."""
    if not since:
        return {}
    try:
        data = json.loads(since)
        if not isinstance(data, dict):
            return {}
        out = {}
        for k in ENTITIES:
            if k in data:
                out[k] = int(data[k])
        return out
    except (ValueError, TypeError):
        return {}


@router.get("/sync/pull")
def sync_pull(
    since: Optional[str] = Query(
        None, description='JSON cursor map, e.g. {"invoice":120,"payment":45}'),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT,
                       description="max rows PER entity per page"),
    current_user: dict = Depends(get_active_user),
    db: Session = Depends(get_db),
):
    """Return tenant-scoped changes since the per-entity id cursor. Append-only
    money entities only (Slice 2); exactly-once, gap-free delivery via id > cursor."""
    bid = current_user["id"]
    cur = _parse_since(since)

    changes: dict = {}
    new_cursor: dict = {}
    has_more = False

    for key, Model, ser in _FEED:
        c = cur.get(key, 0)
        # +1 sentinel to detect whether more rows exist past this page.
        rows = (
            db.query(Model)
            .filter(Model.business_id == bid, Model.id > c)
            .order_by(Model.id.asc())
            .limit(limit + 1)
            .all()
        )
        more = len(rows) > limit
        rows = rows[:limit]
        changes[key] = [ser(r) for r in rows]
        new_cursor[key] = rows[-1].id if rows else c
        has_more = has_more or more

    logger.info(
        "[SYNC] pull biz=%s since=%s -> counts=%s has_more=%s",
        bid, cur, {k: len(v) for k, v in changes.items()}, has_more,
    )
    return {"changes": changes, "cursor": new_cursor, "has_more": has_more, "limit": limit}
