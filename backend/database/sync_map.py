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
from typing import Any, Dict

from database.models import (
    User, Customer, Vendor, Product, Invoice, InvoiceLineItem,
    Inventory, Payment, StockLedger, ProductBarcode, BusinessSettings,
    InvoicePayment, SharedLedger, Expense, Godown, StockTransfer,
    StockTransferLineItem, PurchaseInvoice, PurchaseInvoiceLineItem,
    PurchaseOrder, PurchaseOrderLineItem, AlertConfig, RateLimitConfig,
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
    "payments": Payment,
    "stock_ledger": StockLedger,
    "product_barcodes": ProductBarcode,
    "business_settings": BusinessSettings,
    "invoice_payments": InvoicePayment,
    "shared_ledgers": SharedLedger,
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
}

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
