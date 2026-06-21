"""
core/catalog/barcode.py — multi-barcode resolution for billing.
===============================================================
One product accumulates MANY barcodes over time (packaging revisions, new
cartons, supplier variants). At the billing counter a scan must resolve to the
ONE right product, and adding a freshly-seen code to a known product must be
trivial. This module owns that.

Conventions (FOUNDATION.md): scoped by `business_id`; functions take an open
`db` Session and DO NOT commit (the caller's command owns the transaction).

  resolve_barcode(db, business_id, code)        scan → Product (or None)
  add_barcode(db, business_id, product_id, code) attach a new code (conflict-safe)
  list_barcodes(db, business_id, product_id)     all codes for a product
  set_primary(db, business_id, product_id, code) choose the label/display code
  deactivate(db, business_id, code)              retire a code without deleting
"""
import logging
from typing import Optional

from core.models import ProductBarcode        # core-owned table
from database.models import Product             # shared table

logger = logging.getLogger("bizassist.product_barcode")


def _norm(code: str) -> str:
    """Normalize a scanned/typed barcode (trim + drop stray spaces)."""
    return "".join((code or "").split())


class BarcodeConflict(Exception):
    """Raised when a code is already mapped to a DIFFERENT product."""
    def __init__(self, code: str, existing_product_id: int):
        self.code = code
        self.existing_product_id = existing_product_id
        super().__init__(f"barcode '{code}' already maps to product {existing_product_id}")


# ── Resolve: scan → product (the billing-counter hot path) ───────────────────

def resolve_barcode(db, business_id: int, code: str) -> Optional[Product]:
    """
    Return the Product a scanned code maps to (active codes first), or None.
    Falls back to the legacy `Product.barcode` column so pre-existing single-
    barcode products still scan during/after migration.
    """
    code = _norm(code)
    if not code:
        return None

    # A code KNOWN to the barcode table resolves there (active → its product;
    # retired → None). Only a code with NO barcode row at all falls back to the
    # legacy single `Product.barcode`. This stops a retired code leaking through
    # the legacy path (it may still equal a product's mirrored primary).
    row = (
        db.query(ProductBarcode)
        .filter(ProductBarcode.business_id == business_id,
                ProductBarcode.barcode == code)
        .first()
    )
    if row is not None:
        if row.active:
            return db.query(Product).filter(Product.id == row.product_id).first()
        return None

    # Legacy fallback: products that still carry a single `barcode` value.
    return (
        db.query(Product)
        .filter(Product.business_id == business_id, Product.barcode == code)
        .first()
    )


# ── Add: attach a newly-seen code to a known product ─────────────────────────

def add_barcode(db, business_id: int, product_id: int, code: str, *,
                make_primary: bool = False, label: Optional[str] = None,
                source: str = "manual") -> ProductBarcode:
    """
    Attach `code` to `product_id`. Conflict-safe:
      • already attached to THIS product → return the existing row (idempotent),
        reactivating it if it was retired.
      • attached to ANOTHER product → raise BarcodeConflict (the caller decides:
        warn the user / reassign — never silently steal a code).
    First barcode for a product auto-becomes primary.
    """
    code = _norm(code)
    if not code:
        raise ValueError("empty barcode")

    # Flush so rows added earlier in THIS transaction are visible to the lookups
    # below (otherwise a same-transaction duplicate isn't seen → UNIQUE violation,
    # and `has_any` misjudges whether this is the product's first code).
    db.flush()

    existing = (
        db.query(ProductBarcode)
        .filter(ProductBarcode.business_id == business_id,
                ProductBarcode.barcode == code)
        .first()
    )
    if existing:
        if existing.product_id != product_id:
            raise BarcodeConflict(code, existing.product_id)
        existing.active = True          # re-activate if it was retired
        if make_primary:
            set_primary(db, business_id, product_id, code)
        return existing

    has_any = (
        db.query(ProductBarcode)
        .filter(ProductBarcode.business_id == business_id,
                ProductBarcode.product_id == product_id)
        .first()
        is not None
    )
    primary = make_primary or not has_any   # first code is primary by default

    row = ProductBarcode(
        business_id=business_id, product_id=product_id, barcode=code,
        is_primary=primary, active=True, label=label, source=source,
    )
    db.add(row)
    db.flush()                          # make the new row visible to the flag query
    if primary:
        _set_primary_flag(db, business_id, product_id, code)
        _mirror_primary_to_product(db, business_id, product_id, code)
    logger.info("[BARCODE] +%s → product %s (primary=%s, src=%s)",
                code, product_id, primary, source)
    return row


# ── List / primary / retire ──────────────────────────────────────────────────

def list_barcodes(db, business_id: int, product_id: int, include_inactive: bool = True):
    q = db.query(ProductBarcode).filter(
        ProductBarcode.business_id == business_id,
        ProductBarcode.product_id == product_id,
    )
    if not include_inactive:
        q = q.filter(ProductBarcode.active == True)  # noqa: E712
    return q.order_by(ProductBarcode.is_primary.desc(), ProductBarcode.id.asc()).all()


def set_primary(db, business_id: int, product_id: int, code: str) -> None:
    """Make `code` the product's primary/display barcode (exactly one primary)."""
    code = _norm(code)
    db.flush()   # ensure all of this product's pending barcode rows are visible
    _set_primary_flag(db, business_id, product_id, code)
    _mirror_primary_to_product(db, business_id, product_id, code)


def deactivate(db, business_id: int, code: str) -> bool:
    """Retire a code (keep it for history; old stock still resolves)."""
    code = _norm(code)
    row = (
        db.query(ProductBarcode)
        .filter(ProductBarcode.business_id == business_id,
                ProductBarcode.barcode == code)
        .first()
    )
    if not row:
        return False
    row.active = False
    return True


# ── internals ────────────────────────────────────────────────────────────────

def _set_primary_flag(db, business_id: int, product_id: int, code: str) -> None:
    for r in db.query(ProductBarcode).filter(
        ProductBarcode.business_id == business_id,
        ProductBarcode.product_id == product_id,
    ).all():
        r.is_primary = (r.barcode == code)


def _mirror_primary_to_product(db, business_id: int, product_id: int, code: str) -> None:
    """Keep the legacy `Product.barcode` cache pointing at the primary code."""
    p = db.query(Product).filter(Product.id == product_id,
                                 Product.business_id == business_id).first()
    if p is not None:
        p.barcode = code
