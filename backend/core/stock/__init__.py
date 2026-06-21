"""core.stock — append-only stock ledger (the inventory truth)."""
from core.stock.ledger import (  # noqa: F401
    record_movement, current_stock, rebuild_inventory_cache,
    MOVEMENT_TYPES,
    PURCHASE, SALE, RETURN_IN, RETURN_OUT, DAMAGE,
    ADJUSTMENT, ORDER_RESERVED, ORDER_RELEASED, OPENING,
)
