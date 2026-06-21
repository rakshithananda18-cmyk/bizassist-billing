"""
services/stock_ledger.py — COMPATIBILITY SHIM (moved to core/).
==============================================================
The real implementation now lives in `core/stock/ledger.py` (the billing
ecosystem core, kept separate from this AI/legacy `services/` package). This
shim re-exports it so any old import path `from services import stock_ledger`
keeps working. New code should import `from core.stock import ledger`.
"""
from core.stock.ledger import (  # noqa: F401
    record_movement, current_stock, rebuild_inventory_cache,
    _refresh_inventory_cache,
    MOVEMENT_TYPES,
    PURCHASE, SALE, RETURN_IN, RETURN_OUT, DAMAGE,
    ADJUSTMENT, ORDER_RESERVED, ORDER_RELEASED, OPENING,
)
