"""core.catalog — product catalogue concerns (multi-barcode resolution)."""
from core.catalog.barcode import (  # noqa: F401
    resolve_barcode, add_barcode, list_barcodes, set_primary, deactivate,
    BarcodeConflict,
)
