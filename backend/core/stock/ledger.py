"""
core/stock/ledger.py — the append-only stock ledger (billing foundation, D4).
=============================================================================
The FIRST core module and the template for every domain module (see
FOUNDATION.md). It owns one job: record stock movements and report stock, with:

  • APPEND-ONLY — `record_movement()` only ever INSERTs. Stock never goes up or
    down by editing a number; it changes because a movement was recorded. A
    correction is a new (signed) `adjustment` row, never an overwrite.
  • LEDGER IS TRUTH — `current_stock()` is the SUM of movements. `inventory.stock`
    is only a cached projection that `record_movement()` keeps in step and that
    `rebuild_inventory_cache()` can always recompute from scratch.
  • COMPOSABLE — functions take an open `db` Session and DO NOT commit. The
    calling command handler owns the transaction, so a sale (invoice + stock
    movement) commits atomically or not at all. (FOUNDATION.md → "Command handlers".)

No business logic about *why* a movement happens lives here — that belongs to the
billing/purchase/order modules, which call `record_movement()`.
"""
import logging
from typing import Optional

from sqlalchemy import func

from core.models import StockLedger          # core-owned table
from database.models import Inventory, Product          # shared table (cache projection)

logger = logging.getLogger("bizassist.stock_ledger")


# ── Movement vocabulary ──────────────────────────────────────────────────────
# Canonical set; the sign is enforced by the caller's qty_delta, but these note
# the expected direction so callers (and tests) stay consistent.
PURCHASE        = "purchase"         # +  goods received from a supplier
SALE            = "sale"             # -  goods sold on an invoice
RETURN_IN       = "return_in"        # +  customer returned goods
RETURN_OUT      = "return_out"       # -  goods returned to a supplier
DAMAGE          = "damage"           # -  write-off / breakage / expiry
ADJUSTMENT      = "adjustment"       # ±  manual correction (signed)
ORDER_RESERVED  = "order_reserved"   # -  soft-held for an open order
ORDER_RELEASED  = "order_released"   # +  reservation released
OPENING         = "opening"          # +  opening balance (switch-in import)
TRANSFER_OUT    = "transfer_out"     # -  goods transferred out of a godown
TRANSFER_IN     = "transfer_in"      # +  goods transferred into a godown

MOVEMENT_TYPES = frozenset({
    PURCHASE, SALE, RETURN_IN, RETURN_OUT, DAMAGE,
    ADJUSTMENT, ORDER_RESERVED, ORDER_RELEASED, OPENING,
    TRANSFER_OUT, TRANSFER_IN,
})


# ── Read: stock is the SUM of the ledger (truth) ─────────────────────────────

def current_stock(db, business_id: int, *,
                  product_id: Optional[int] = None,
                  product_name: Optional[str] = None,
                  godown_id: Optional[int] = None,
                  batch_no: Optional[str] = None) -> float:
    """
    The authoritative quantity for a product = SUM(qty_delta) over its ledger.
    Identify the product by product_id (preferred) or product_name. Returns 0.0
    if there are no movements. This is what `inventory.stock` is a cache of.
    """
    q = db.query(func.coalesce(func.sum(StockLedger.qty_delta), 0.0)).filter(
        StockLedger.business_id == business_id
    )
    if product_id is not None:
        q = q.filter(StockLedger.product_id == product_id)
    elif product_name is not None:
        q = q.filter(StockLedger.product_name == product_name)
    else:
        raise ValueError("current_stock needs product_id or product_name")

    if godown_id is not None:
        q = q.filter(StockLedger.godown_id == godown_id)
    if batch_no is not None:
        q = q.filter(StockLedger.batch_no == batch_no)

    return float(q.scalar() or 0.0)


# ── Write: the ONLY way stock changes (append-only) ──────────────────────────

def record_movement(db, *, business_id: int, movement_type: str, qty_delta: float,
                    product_id: Optional[int] = None,
                    product_name: Optional[str] = None,
                    reference_type: Optional[str] = None,
                    reference_id: Optional[int] = None,
                    note: Optional[str] = None,
                    device_id: Optional[str] = None,
                    godown_id: Optional[int] = None,
                    batch_no: Optional[str] = None,
                    expiry_date: Optional[str] = None,
                    update_cache: bool = True) -> StockLedger:
    """
    Append ONE stock movement. Does not commit — the caller's command owns the
    transaction. Computes `balance_after` and (optionally) refreshes the
    `inventory.stock` cache so reads are fast. Returns the new StockLedger row.

    Raises ValueError on an unknown movement_type or a missing product key.
    """
    if movement_type not in MOVEMENT_TYPES:
        raise ValueError(f"unknown movement_type '{movement_type}'")
    if product_id is None and not product_name:
        raise ValueError("record_movement needs product_id or product_name")

    # Flush so earlier movements added in THIS transaction (not yet committed)
    # are visible to the SUM below — otherwise `prior` ignores them and the
    # running balance is wrong for consecutive movements before a commit.
    db.flush()
    prior = current_stock(db, business_id, product_id=product_id, product_name=product_name,
                          godown_id=godown_id, batch_no=batch_no)
    balance_after = prior + float(qty_delta)

    row = StockLedger(
        business_id=business_id,
        product_id=product_id,
        product_name=product_name,
        movement_type=movement_type,
        qty_delta=float(qty_delta),
        balance_after=balance_after,
        reference_type=reference_type,
        reference_id=reference_id,
        note=note,
        device_id=device_id,
        godown_id=godown_id,
        batch_no=batch_no,
        expiry_date=expiry_date,
    )
    db.add(row)

    if update_cache:
        _refresh_inventory_cache(db, business_id, product_id=product_id,
                                 product_name=product_name, new_balance=balance_after,
                                 godown_id=godown_id, batch_no=batch_no, expiry_date=expiry_date)

    logger.info("[STOCK] %s %s%.3f product=%s ref=%s/%s godown=%s batch=%s → %.3f",
                movement_type, "+" if qty_delta >= 0 else "", qty_delta,
                product_id or product_name, reference_type, reference_id,
                godown_id, batch_no, balance_after)
    return row


# ── Cache projection (rebuildable; never the source of truth) ────────────────

def _refresh_inventory_cache(db, business_id: int, *, product_id, product_name, new_balance,
                             godown_id=None, batch_no=None, expiry_date=None) -> None:
    """Keep `inventory.stock` in step with the ledger. Best-effort: a missing
    inventory row is fine (ledger is still the truth)."""
    q = db.query(Inventory).filter(Inventory.business_id == business_id)
    if product_id is not None:
        q = q.filter(Inventory.product_id == product_id)
    elif product_name:
        q = q.filter(Inventory.product_name == product_name)
    
    q = q.filter(Inventory.godown_id == godown_id)
    q = q.filter(Inventory.batch_no == batch_no)

    inv = q.first()
    if inv is not None:
        inv.stock = int(round(new_balance))
        if expiry_date:
            inv.expiry_date = expiry_date
    else:
        # Create it on the fly if product_id is not None
        if product_id is not None:
            prod = db.query(Product).filter(Product.id == product_id, Product.business_id == business_id).first()
            if prod:
                inv = Inventory(
                    business_id=business_id,
                    product_id=product_id,
                    product_name=prod.name,
                    stock=int(round(new_balance)),
                    godown_id=godown_id,
                    batch_no=batch_no,
                    expiry_date=expiry_date,
                    unit=prod.unit,
                    hsn_sac=prod.hsn_sac,
                    barcode=prod.barcode,
                    selling_price=prod.selling_price,
                    cost_price=prod.cost_price,
                    mrp=prod.mrp,
                    category=prod.category,
                )
                db.add(inv)


def rebuild_inventory_cache(db, business_id: int) -> int:
    """
    Recompute every `inventory.stock` for a business from the ledger (repair /
    audit). Returns the number of inventory rows updated. Proof that the cache
    is disposable and the ledger is the truth.
    """
    rows = db.query(Inventory).filter(Inventory.business_id == business_id).all()
    updated = 0
    for inv in rows:
        bal = current_stock(db, business_id,
                            product_id=inv.product_id,
                            product_name=inv.product_name,
                            godown_id=inv.godown_id,
                            batch_no=inv.batch_no)
        new = int(round(bal))
        if inv.stock != new:
            inv.stock = new
            updated += 1
    return updated
