"""
services/billing.py — COMPATIBILITY SHIM (moved to core/).
=========================================================
The real implementation now lives in `core/billing/commands.py` (the billing
ecosystem core, kept separate from this AI/legacy `services/` package). This
shim re-exports it so any old import path `from services import billing` keeps
working. New code should import `from core.billing import commands` (or just
`from core.billing import create_sale_invoice`).
"""
from core.billing.commands import (  # noqa: F401
    create_sale_invoice,
    _compute_line, _line_rates, _is_intra_state, _state_code,
    _next_invoice_number, _round2,
)
