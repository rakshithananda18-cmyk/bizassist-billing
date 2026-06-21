"""
services/product_barcode.py — COMPATIBILITY SHIM (moved to core/).
=================================================================
The real implementation now lives in `core/catalog/barcode.py` (the billing
ecosystem core, kept separate from this AI/legacy `services/` package). This
shim re-exports it so any old import path `from services import product_barcode`
keeps working. New code should import `from core.catalog import barcode`.
"""
from core.catalog.barcode import (  # noqa: F401
    resolve_barcode, add_barcode, list_barcodes, set_primary, deactivate,
    BarcodeConflict,
    _norm, _set_primary_flag, _mirror_primary_to_product,
)
