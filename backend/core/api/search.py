"""
core/api/search.py
==================
One endpoint behind the universal search palette.

WHY ONE ENDPOINT, not a client fan-out across the four existing `?q=` routes:

  * four round trips per keystroke instead of one;
  * `/customers?q=` runs `_compute_customer_stats` PER ROW (parties.py) — an
    N+1 that is fine for a settings page and wrong for search-as-you-type;
  * there is no invoice search anywhere, so one of the four would have to be
    written regardless;
  * `authFetch` raises a toast on every non-2xx (contexts/AuthContext.jsx), so a
    fan-out turns one bad keystroke into four toasts.

WHY IT NEVER RAISES: this is called on every keystroke. A 422 for a
half-typed word would toast the owner while they are still typing, so a bad or
empty query returns 200 with an empty list. The only thing worth failing on is
authentication, which the dependency handles before the body runs.

Tenant scoping is the non-negotiable part: every branch filters on the resolved
business id. See core/identity.py — an integer id means nothing outside the
database that issued it, so it is resolved here rather than taken from the token.
"""
import logging

from fastapi import APIRouter, Depends
from sqlalchemy import or_
from sqlalchemy.orm import Session

from database.db import get_db
from database.models import Customer, Vendor, Invoice, Product
from services.auth import get_active_user, resolve_business_id_in_db

router = APIRouter()
logger = logging.getLogger("bizassist.search")

# Per-kind cap. The palette shows a handful of each and the point is to pick one,
# not to browse — that is what the list pages are for.
_PER_KIND = 5
_MAX_PER_KIND = 10

# LIKE treats % and _ as wildcards, so an unescaped query is a way to enumerate
# the table: `q=%` becomes `%%%`, which matches every row, and `_` matches any
# single character. Typing one punctuation mark would have dumped records the
# owner never searched for. Escaped with a backslash, declared per-clause below.
_LIKE_ESCAPE = "\\"


def _escape_like(text: str) -> str:
    """Make `text` a literal in a LIKE pattern. The escape character itself goes
    first, or escaping the wildcards would double-escape it."""
    for ch in (_LIKE_ESCAPE, "%", "_"):
        text = text.replace(ch, _LIKE_ESCAPE + ch)
    return text


@router.get("/search")
def universal_search(
    q: str = "",
    limit: int = _PER_KIND,
    current_user: dict = Depends(get_active_user),
    db: Session = Depends(get_db),
):
    """Records matching `q`, across products, customers, vendors and invoices.

    Shape: `{"items": [{kind, id, title, subtitle}]}` — one flat list, already
    ordered by kind, so the client renders it without knowing the schema of any
    of these tables.
    """
    q = (q or "").strip()
    if not q:
        return {"items": []}

    bid = resolve_business_id_in_db(current_user, db)
    per_kind = max(1, min(limit, _MAX_PER_KIND))
    like = f"%{_escape_like(q)}%"
    items: list[dict] = []

    # Cashiers cannot open /stock/purchase, so a vendor hit would be a result
    # that goes nowhere. Same rule the sidebar already applies to that route.
    role = (current_user.get("role") or "").lower()
    is_cashier = role in ("cashier", "supply adder")

    try:
        products = (
            db.query(Product)
            .filter(Product.business_id == bid,
                    or_(Product.name.ilike(like, escape=_LIKE_ESCAPE),
                        Product.sku.ilike(like, escape=_LIKE_ESCAPE),
                        Product.barcode.ilike(like, escape=_LIKE_ESCAPE)))
            .order_by(Product.name.asc())
            .limit(per_kind)
            .all()
        )
        for p in products:
            items.append({
                "kind": "product",
                "id": p.id,
                "title": p.name or "Unnamed product",
                "subtitle": p.sku or p.barcode or "",
            })
    except Exception as e:                                  # noqa: BLE001
        # One table failing must not blank the whole palette — the others are
        # still useful, and a partial answer beats a toast mid-keystroke.
        logger.warning("[SEARCH] product branch failed: %s", e)

    try:
        customers = (
            db.query(Customer)
            .filter(Customer.business_id == bid,
                    or_(Customer.name.ilike(like, escape=_LIKE_ESCAPE), Customer.phone.ilike(like, escape=_LIKE_ESCAPE)))
            .order_by(Customer.name.asc())
            .limit(per_kind)
            .all()
        )
        for c in customers:
            items.append({
                "kind": "customer",
                "id": c.id,
                "title": c.name or "Unnamed customer",
                "subtitle": c.phone or "",
            })
    except Exception as e:                                  # noqa: BLE001
        logger.warning("[SEARCH] customer branch failed: %s", e)

    if not is_cashier:
        try:
            vendors = (
                db.query(Vendor)
                .filter(Vendor.business_id == bid,
                        or_(Vendor.name.ilike(like, escape=_LIKE_ESCAPE), Vendor.phone.ilike(like, escape=_LIKE_ESCAPE)))
                .order_by(Vendor.name.asc())
                .limit(per_kind)
                .all()
            )
            for v in vendors:
                items.append({
                    "kind": "vendor",
                    "id": v.id,
                    "title": v.name or "Unnamed supplier",
                    "subtitle": v.phone or "",
                })
        except Exception as e:                              # noqa: BLE001
            logger.warning("[SEARCH] vendor branch failed: %s", e)

    try:
        invoices = (
            db.query(Invoice)
            .filter(Invoice.business_id == bid,
                    or_(Invoice.invoice_id.ilike(like, escape=_LIKE_ESCAPE), Invoice.customer.ilike(like, escape=_LIKE_ESCAPE)))
            .order_by(Invoice.id.desc())        # newest first — the likely target
            .limit(per_kind)
            .all()
        )
        for inv in invoices:
            amount = f"₹{inv.amount:,.0f}" if inv.amount is not None else ""
            who = inv.customer or "Cash Customer"
            items.append({
                "kind": "invoice",
                # The route is keyed by invoice NUMBER, not the row id
                # (App.jsx: /invoice/:invoiceNo/view), so that is what travels.
                "id": inv.invoice_id,
                "title": inv.invoice_id or f"Invoice #{inv.id}",
                "subtitle": " · ".join(x for x in (who, amount, inv.status) if x),
            })
    except Exception as e:                                  # noqa: BLE001
        logger.warning("[SEARCH] invoice branch failed: %s", e)

    return {"items": items}
