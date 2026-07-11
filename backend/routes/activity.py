"""
routes/activity.py — the business activity feed (owner requirement, 2026-07).
=============================================================================
EVERYTHING that happens in the app — billing, stock, settings, staff, shifts,
purchases, B2B — already lands in `table_alterations` (the SQLAlchemy flush
auditor records who/what/when with full before/after values). This route turns
that raw audit into an owner-readable feed:

  GET /activity?limit=&offset=&category=   → newest-first, human summaries
  (old/new values ride along so the UI can show a what-changed diff)

Owner-only: the feed exposes settings diffs and every staff member's actions —
exactly the anti-tamper visibility the owner asked for ("inventory can't be
scammed by the staff").
"""
import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from database.db import get_db
from database.models import TableAlteration, User
from services.auth import require_owner

router = APIRouter()
logger = logging.getLogger("bizassist.routes.activity")

# table → (category, friendly label)
TABLE_MAP = {
    "invoices":                  ("billing",   "Invoice"),
    "invoice_line_items":        ("billing",   "Invoice line"),
    "invoice_payments":          ("payments",  "Payment"),
    "payments":                  ("payments",  "Payment"),
    "products":                  ("stock",     "Product"),
    "inventory":                 ("stock",     "Inventory item"),
    "stock_ledger":              ("stock",     "Stock movement"),
    "product_barcodes":          ("stock",     "Barcode"),
    "godowns":                   ("stock",     "Godown"),
    "stock_transfers":           ("stock",     "Stock transfer"),
    "stock_transfer_line_items": ("stock",     "Transfer line"),
    "customers":                 ("contacts",  "Customer"),
    "vendors":                   ("contacts",  "Supplier"),
    "purchase_invoices":         ("purchases", "Purchase bill"),
    "purchase_invoice_line_items": ("purchases", "Purchase line"),
    "purchase_orders":           ("purchases", "Purchase order"),
    "purchase_order_line_items": ("purchases", "PO line"),
    "users":                     ("settings",  "Account / settings"),
    "business_settings":         ("settings",  "Business settings"),
    "alert_configs":             ("settings",  "Alert config"),
    "register_shifts":           ("shifts",    "Shift"),
    "shift_cash_movements":      ("shifts",    "Cash movement"),
    "expenses":                  ("payments",  "Expense"),
    "b2b_connections":           ("b2b",       "B2B connection"),
    "b2b_invite_codes":          ("b2b",       "B2B invite"),
    "b2b_orders":                ("b2b",       "B2B order"),
    "b2b_order_line_items":      ("b2b",       "B2B order line"),
    "b2b_ledgers":               ("b2b",       "B2B ledger"),
    "journal_entries":           ("books",     "Journal entry"),
    "journal_lines":             ("books",     "Journal line"),
    "period_locks":              ("books",     "Period lock"),
    "business_facts":            ("ai",        "AI memory"),
}
ACTION_VERB = {"INSERT": "created", "UPDATE": "updated", "DELETE": "deleted"}
VALID_CATEGORIES = sorted({c for c, _ in TABLE_MAP.values()})

# Row-name extraction: first present key wins.
_NAME_KEYS = ("invoice_id", "invoice_number", "name", "product_name", "title",
              "code", "username", "bill_number", "reference")


def _loads(blob):
    try:
        return json.loads(blob) if blob else {}
    except Exception:
        return {}


def _summarize(row: TableAlteration) -> dict:
    category, label = TABLE_MAP.get(row.table_name, ("other", row.table_name))
    verb = ACTION_VERB.get((row.action or "").upper(), (row.action or "?").lower())
    new = _loads(row.new_values)
    old = _loads(row.old_values)
    src = new or old

    name = None
    for k in _NAME_KEYS:
        if src.get(k):
            name = str(src[k])
            break

    # Special-case the noisy-but-important ones so they read naturally.
    if row.table_name == "stock_ledger":
        qty = src.get("qty_delta")
        pname = src.get("product_name") or f"product #{src.get('product_id', '?')}"
        mtype = src.get("movement_type") or "movement"
        summary = f"Stock {mtype}: {qty} × {pname}"
    elif row.table_name == "users" and (row.action or "").upper() == "UPDATE":
        changed = sorted(set(new.keys()))
        summary = "Settings updated" if changed == ["settings"] else f"Account updated ({', '.join(changed[:4])}{'…' if len(changed) > 4 else ''})"
    elif row.table_name == "shift_cash_movements":
        summary = f"Cash {str(src.get('movement_type', '')).replace('_', ' ')} ₹{src.get('amount', '?')} ({src.get('category', '')})"
    else:
        summary = f"{label} {verb}" + (f": {name}" if name else "")

    # What-changed diff for updates: only the keys whose values differ.
    changes = None
    if (row.action or "").upper() == "UPDATE" and old and new:
        changes = {k: {"from": old.get(k), "to": new.get(k)}
                   for k in new.keys() if old.get(k) != new.get(k)}

    return {
        "id": row.id,
        "at": row.created_at.isoformat() if row.created_at else None,
        "category": category,
        "label": label,
        "table": row.table_name,
        "action": (row.action or "").upper(),
        "summary": summary,
        "record_id": row.record_id,
        "by_user_id": row.user_id,
        "by_username": row.username,
        "changes": changes,
        "new_values": new or None,
        "old_values": old or None,
    }


@router.get("/activity")
def activity_feed(limit: int = Query(50, ge=1, le=200),
                  offset: int = Query(0, ge=0),
                  category: Optional[str] = None,
                  current_user: dict = Depends(require_owner),
                  db: Session = Depends(get_db)):
    """Newest-first activity for the caller's business. `category` filters to
    one of: billing, stock, payments, settings, shifts, contacts, purchases,
    b2b, books, ai."""
    bid = current_user["id"]
    q = (db.query(TableAlteration)
         .filter(TableAlteration.business_id == bid)
         .order_by(TableAlteration.id.desc()))
    if category:
        tables = [t for t, (c, _) in TABLE_MAP.items() if c == category]
        if not tables:
            raise HTTPException(status_code=400,
                                detail=f"Unknown category. Valid: {', '.join(VALID_CATEGORIES)}")
        q = q.filter(TableAlteration.table_name.in_(tables))
    total = q.count()
    rows = q.offset(offset).limit(limit).all()

    # Resolve display names for staff attribution in one query.
    uids = {r.user_id for r in rows if r.user_id}
    names = {}
    if uids:
        for u in db.query(User).filter(User.id.in_(uids)).all():
            names[u.id] = u.staff_login_name or u.username
    items = []
    for r in rows:
        d = _summarize(r)
        if d["by_user_id"] in names:
            d["by_username"] = names[d["by_user_id"]]
        items.append(d)

    return {"items": items, "total": total,
            "categories": VALID_CATEGORIES}
