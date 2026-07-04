"""
database/sync_map.py
====================
Single source of truth for the hybrid-sync table→model mapping and the
entity→broadcast-channel mapping.

(R-7) Previously this map was duplicated verbatim in `routes/sync.py` and
`services/sync_worker.py`. A table added to one but not the other silently
stopped syncing in one direction. Both modules now import from here so they
can never drift.
"""
import logging
from typing import Any, Dict

from sqlalchemy import text

from database.models import (
    User, Customer, Vendor, Product, Invoice, InvoiceLineItem,
    Inventory, LegacyPayment, StockLedger, ProductBarcode, BusinessSettings,
    InvoicePayment, B2BLedger, Expense, Godown, StockTransfer,
    StockTransferLineItem, PurchaseInvoice, PurchaseInvoiceLineItem,
    PurchaseOrder, PurchaseOrderLineItem, AlertConfig, RateLimitConfig,
    TableAlteration,
)

# table name -> SQLAlchemy ORM model
MODEL_MAP: Dict[str, Any] = {
    # NOTE: `users` is intentionally NOT synced. Identity is established by
    # registration/login and resolved by BizID/username — copying a user row
    # across databases carries its PK + UNIQUE public_id (BizID), which collides
    # (e.g. local id=122 and cloud id=7 share the unified BizID → UNIQUE failed).
    # Only business *data* syncs; the account/identity does not.
    "customers": Customer,
    "vendors": Vendor,
    "products": Product,
    "invoices": Invoice,
    "invoice_line_items": InvoiceLineItem,
    "inventory": Inventory,
    "payments": LegacyPayment,
    "stock_ledger": StockLedger,
    "product_barcodes": ProductBarcode,
    "business_settings": BusinessSettings,
    "invoice_payments": InvoicePayment,
    "b2b_ledgers": B2BLedger,
    "expenses": Expense,
    "godowns": Godown,
    "stock_transfers": StockTransfer,
    "stock_transfer_line_items": StockTransferLineItem,
    "purchase_invoices": PurchaseInvoice,
    "purchase_invoice_line_items": PurchaseInvoiceLineItem,
    "purchase_orders": PurchaseOrder,
    "purchase_order_line_items": PurchaseOrderLineItem,
    "alert_configs": AlertConfig,
    "rate_limit_configs": RateLimitConfig,
    "table_alterations": TableAlteration,
}

logger = logging.getLogger("bizassist.sync_map")


def resolve_parent_fk_uids(db, model_cls, data: dict, log_prefix: str = "sync") -> bool:
    """(Step 3 / R-3) Resolve a synced row's parent foreign keys from the durable
    parent ``uid`` carried in the payload (``<fk>_uid`` / ``<base>_uid``),
    rewriting each FK column to the LOCAL parent id.

    Single source of truth for both apply paths — ``routes/sync.py::push_changes``
    and ``services/sync_worker.py`` pull-apply — so the resolution/deferral logic
    can never drift between them.

    Returns ``True`` if the row must be **deferred**: a parent ``uid`` was provided
    but its parent row isn't in this DB yet (child arrived before parent). The
    caller skips it; it re-applies on a later sync once the parent lands. Writing
    the source-DB integer id instead would create a wrong-row / orphan link.
    Mutates ``data[fk_col]`` in place on each successful resolution.
    """
    for fk in model_cls.__table__.foreign_keys:
        fk_col = fk.parent.name
        parent_table = fk.column.table.name

        parent_uid_val = None
        for suffix in [f"{fk_col}_uid", f"{fk_col[:-3]}_uid" if fk_col.endswith("_id") else ""]:
            if suffix and suffix in data:
                parent_uid_val = data[suffix]
                break

        if parent_uid_val:
            try:
                row = db.execute(
                    text(f'SELECT "{fk.column.name}" FROM "{parent_table}" WHERE uid = :uid'),
                    {"uid": parent_uid_val},
                ).fetchone()
                if row:
                    data[fk_col] = row[0]
                else:
                    logger.info(
                        "%s: deferring %s — parent %s uid=%s not in this DB yet",
                        log_prefix, getattr(model_cls, "__tablename__", model_cls),
                        parent_table, parent_uid_val,
                    )
                    return True
            except Exception as e:
                logger.warning(
                    "%s: failed to resolve FK %s via uid %s: %s",
                    log_prefix, fk_col, parent_uid_val, e,
                )
    return False


# table name -> SSE channel name used to nudge the browser to refetch
ENTITY_BROADCAST_MAP: Dict[str, str] = {
    "customers": "party",
    "vendors": "party",
    "products": "product",
    "invoices": "invoice",
    "payments": "payment",
    "invoice_payments": "payment",
    "purchase_invoices": "purchase",
    "godowns": "godown",
    "purchase_orders": "order",
    "stock_transfers": "stock",
    "stock_ledger": "stock",
    "business_settings": "settings",
}
